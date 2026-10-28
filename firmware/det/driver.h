#ifndef DET_DRIVER_H
#define DET_DRIVER_H
#include <stdint.h>
#include <stddef.h>
#include "spec.h"
static inline void det_fence(void){__asm__ volatile("fence iorw,iorw" ::: "memory");}
static inline uint32_t ticks(void){uint32_t x;__asm__ volatile("rdcycle %0":"=r"(x));return x;}
void text(const char *s);void num(uint32_t x);void die(const char *s);
int det_conv(uint32_t desc);
int8_t det_requant(int32_t x,uint32_t m,uint32_t s);
uint32_t det_hash(const int8_t *p,uint32_t n);
void det_cpu_conv(const uint32_t *d);
#endif
