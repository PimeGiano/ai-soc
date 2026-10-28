ENTRY(_start)
MEMORY {
 CODE (rx) : ORIGIN = 0, LENGTH = 64K
 DATA (rw) : ORIGIN = 0x01000000, LENGTH = 32K
}
SECTIONS {
 .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) *(.srodata*) } > CODE
 .data : { . = ALIGN(4); __global_pointer$ = . + 0x800; *(.sdata*) *(.data*) } > DATA
 .bss (NOLOAD) : { . = ALIGN(4); _bss_start = .; *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(4); _bss_end = .; } > DATA
 _stack_top = 0x05000000;
 ASSERT(_bss_end <= 0x01008000, "firmware data exceeds reserve")
}
