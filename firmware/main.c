#include "driver.h"

// Host graph header fixed at 0x01008000: magic, nops, ops_addr, mode.
// 24-word records: type, src0, src1, dst, H,W,C0,C1,R0,ORDER,M0,S0,M1,S1,
// descriptor, expected_hash, nbytes, layer_id, pool_size, pool_stride, roi_id, flags,0,0.
// The input domain is only 256 INT8 values. Build exact integer conversion
// tables once per operator instead of doing a 64-bit requantization per pixel.
static void conversion_table(int8_t table[256], uint32_t multiplier, uint32_t shift)
{
	for (int v = -128; v < 128; v++)
		table[(uint8_t)v] = det_requant(v, multiplier, shift);
}

// GCC may_alias permits aligned word accesses to the byte tensor storage.
typedef uint32_t tensor_word __attribute__((__may_alias__));

static int identity_scale(uint32_t multiplier, uint32_t shift)
{
	return shift < 31 && multiplier == (1u << shift);
}

static void converted_copy(
	int8_t *dst, const int8_t *src, uint32_t n, const int8_t table[256], int identity)
{
	while (n && (((uintptr_t)dst | (uintptr_t)src) & 3u)) {
		int8_t v = *src++;
		*dst++ = identity ? (v == -128 ? -127 : v) : table[(uint8_t)v];
		n--;
	}
	while (n >= 4) {
		uint32_t word = *(const tensor_word *)src;
		if (identity) {
			// Exact per-byte 0x80 -> 0x81 saturation, with no cross-byte carry.
			uint32_t t = word ^ 0x80808080u;
			uint32_t zero = ~(((t & 0x7f7f7f7fu) + 0x7f7f7f7fu) | t | 0x7f7f7f7fu);
			word |= (zero & 0x80808080u) >> 7;
		} else {
			word = (uint8_t)table[word & 255u] |
				((uint32_t)(uint8_t)table[(word >> 8) & 255u] << 8) |
				((uint32_t)(uint8_t)table[(word >> 16) & 255u] << 16) |
				((uint32_t)(uint8_t)table[word >> 24] << 24);
		}
		*(tensor_word *)dst = word;
		dst += 4;
		src += 4;
		n -= 4;
	}
	while (n--) {
		int8_t v = *src++;
		*dst++ = identity ? (v == -128 ? -127 : v) : table[(uint8_t)v];
	}
}

static void materialize(const uint32_t *o)
{
	const int8_t *a = (const int8_t *)o[1], *b = (const int8_t *)o[2];
	int8_t *y = (int8_t *)o[3];
	uint32_t h = o[4], w = o[5], c0 = o[6], c1 = o[7], r = o[8];
	int8_t low_table[256], high_table[256];
	int low_identity = identity_scale(o[10], o[11]);
	int high_identity = identity_scale(o[12], o[13]);
	if (!low_identity)
		conversion_table(low_table, o[10], o[11]);
	if (!high_identity)
		conversion_table(high_table, o[12], o[13]);

	for (uint32_t iy = 0; iy < h; iy++) {
		const int8_t *low_row = a + (iy / r) * (w / r) * c0;
		for (uint32_t ix = 0; ix < w; ix++) {
			const int8_t *low = low_row + (ix / r) * c0;
			const int8_t *high = b + (iy * w + ix) * c1;
			int8_t *dst = y + (iy * w + ix) * (c0 + c1);
			int8_t *low_dst = dst + (o[9] ? c1 : 0);
			int8_t *high_dst = dst + (o[9] ? 0 : c0);
			converted_copy(low_dst, low, c0, low_table, low_identity);
			converted_copy(high_dst, high, c1, high_table, high_identity);
		}
	}
}

static void pool(const uint32_t *o, int hardware)
{
	const int8_t *x = (const int8_t *)o[1];
	int8_t *y = (int8_t *)o[3];
	uint32_t h = o[4], w = o[5], c = o[6], k = o[18], st = o[19];
	uint32_t ho = (h + 1 - k) / st + 1, wo = (w + 1 - k) / st + 1;
	if (hardware && k == 2) {
		if (det_pool(o[1], o[3], h, w, c, st))
			die("pool accelerator");
		return;
	}

	for (uint32_t oy = 0; oy < ho; oy++)
		for (uint32_t ox = 0; ox < wo; ox++) {
			uint32_t iy = oy * st, ix = ox * st;
			const int8_t *top = x + (iy * w + ix) * c;
			int8_t *dst = y + (oy * wo + ox) * c;
			if (k == 2 && iy < h && ix < w) {
				// Hoist all spatial address arithmetic and border checks out
				// of the channel loop. Darknet pads right/bottom with -127.
				for (uint32_t ch = 0; ch < c; ch++) {
					int8_t v = top[ch];
					if (ix + 1 < w && top[c + ch] > v)
						v = top[c + ch];
					if (iy + 1 < h) {
						const int8_t *bottom = top + w * c;
						if (bottom[ch] > v)
							v = bottom[ch];
						if (ix + 1 < w && bottom[c + ch] > v)
							v = bottom[c + ch];
					}
					dst[ch] = v < -127 ? -127 : v;
				}
			} else {
				for (uint32_t ch = 0; ch < c; ch++) {
					int8_t v = -127;
					for (uint32_t ky = 0; ky < k; ky++)
						for (uint32_t kx = 0; kx < k; kx++)
							if (iy + ky < h && ix + kx < w) {
								int8_t t = x[((iy + ky) * w + ix + kx) * c + ch];
								if (t > v)
									v = t;
							}
					dst[ch] = v;
				}
			}
		}
}

static void slice(const uint32_t *o)
{
	const int8_t *x = (const int8_t *)o[1];
	int8_t *y = (int8_t *)o[3];

	for (uint32_t p = 0; p < o[4] * o[5]; p++)
		memcpy(y + p * o[7], x + p * o[6] + o[8], o[7]);
}

extern void det_postprocess(const uint32_t *header);

static void upsample(const uint32_t *o)
{
	const int8_t *x = (const int8_t *)o[1];
	int8_t *y = (int8_t *)o[3];
	uint32_t h = o[4], w = o[5], c = o[6], r = o[8];
	int8_t table[256];
	int identity = identity_scale(o[10], o[11]);
	if (!identity)
		conversion_table(table, o[10], o[11]);

	for (uint32_t iy = 0; iy < h; iy++)
		for (uint32_t ix = 0; ix < w; ix++) {
			const int8_t *src = x + ((iy / r) * (w / r) + ix / r) * c;
			int8_t *dst = y + (iy * w + ix) * c;
			converted_copy(dst, src, c, table, identity);
		}
}

int main(void)
{
	const uint32_t *h = (const uint32_t *)0x01008000u;

	if (h[0] != 0x44455431u)
		die("graph magic");

	if (*(volatile uint32_t *)(DET_BASE + DET_REG_VERSION) != DET_VERSION)
		die("version");
	const uint32_t *ops = (const uint32_t *)h[2];
	uint32_t mode = h[3], whole = h[7];

	if (whole) {
		det_fence();
		*(volatile uint32_t *)0x20000008u = 0x8000fffeu;
	}

	for (uint32_t i = 0; i < h[1]; i++) {
		const uint32_t *o = ops + i * 24;
		uint32_t roi = o[20];

		if (roi && !whole) {
			det_fence();
			*(volatile uint32_t *)0x20000008u = 0x80000000u | roi;
		}

		if (o[0] == 1) {
			if (mode == 2)
				det_cpu_conv((const uint32_t *)o[14]);
			else {
				int e = det_conv(o[14]);

				if (e) {
					num((uint32_t)-e);
					die("conv");
				}
			}
		} else if (o[0] == 2)
			pool(o, mode != 2);
		else if (o[0] == 3)
			materialize(o);
		else if (o[0] == 4)
			slice(o);
		else if (o[0] == 5)
			upsample(o);
		else
			die("op");

		if (o[21] && !whole) {
			det_fence();
			*(volatile uint32_t *)0x20000008u = o[21];
		}
	}

	if (whole) {
		det_fence();
		*(volatile uint32_t *)0x20000008u = 0x0000fffeu;
	}

	// Verification and printing are outside all measurement regions.
	for (uint32_t i = 0; i < h[1]; i++) {
		const uint32_t *o = ops + i * 24;

		if (det_hash((const int8_t *)o[3], o[16]) != o[15]) {
			text("layer ");
			num(o[17]);
			die("hash");
		}

		text("LAYER ");
		num(o[17]);
		text(" PASS\n");
	}

	det_fence();
	*(volatile uint32_t *)0x20000008u = 0x8000fffdu;
	det_postprocess(h);
	det_fence();
	*(volatile uint32_t *)0x20000008u = 0x0000fffdu;
	text("DETECTION GRAPH PASS\n");
	*(volatile uint32_t *)0x20000004u = 1;

	for (;;) {
	}
}
