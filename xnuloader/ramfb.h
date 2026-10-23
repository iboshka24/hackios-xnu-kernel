#ifndef XNULOADER_RAMFB_H
#define XNULOADER_RAMFB_H
#include <stdint.h>

/* QEMU's ramfb is limited by bochs-vbe.h, independently of iOS's logical display. */
#define RAMFB_WIDTH 1125u
#define RAMFB_HEIGHT 2048u
#define RAMFB_DMA_ERROR 1u
#define RAMFB_DMA_POLLS 100u
#define RAMFB_DMA_POLL_US 100u

static inline uint32_t
ramfb_wait_dma(volatile uint32_t *control, void (*wait_us)(uint32_t))
{
	for (unsigned i = 0; i < RAMFB_DMA_POLLS; i++) {
		uint32_t status = __builtin_bswap32(*control);
		if (status == 0 || (status & RAMFB_DMA_ERROR) != 0) {
			return status;
		}
		wait_us(RAMFB_DMA_POLL_US);
	}
	return __builtin_bswap32(*control);
}
#endif
