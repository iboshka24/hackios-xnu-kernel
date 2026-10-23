/* The loader's actual DMA wait with a simulated fw_cfg device. */
#include <assert.h>
#include <stdio.h>
#include "../xnuloader/ramfb.h"

static volatile uint32_t control;
static unsigned calls, finish_at;
static uint32_t finish_status;

static void
tick(uint32_t microseconds)
{
	assert(microseconds == RAMFB_DMA_POLL_US);
	if (++calls == finish_at) {
		control = __builtin_bswap32(finish_status);
	}
}

static void
check(unsigned finish, uint32_t value, uint32_t expected, unsigned expected_calls)
{
	control = __builtin_bswap32(0x00250018u);
	calls = 0;
	finish_at = finish;
	finish_status = value;
	assert(ramfb_wait_dma(&control, tick) == expected);
	assert(calls == expected_calls);
}

int
main(void)
{
	control = 0;
	calls = 0;
	assert(ramfb_wait_dma(&control, tick) == 0 && calls == 0);
	check(3, 0, 0, 3);
	check(2, RAMFB_DMA_ERROR, RAMFB_DMA_ERROR, 2);
	check(0, 0, 0x00250018u, RAMFB_DMA_POLLS);
	check(RAMFB_DMA_POLLS, 0, 0, RAMFB_DMA_POLLS);
	assert(RAMFB_WIDTH <= 2560u && RAMFB_HEIGHT <= 2048u);
	puts("PASS ramfb: immediate, asynchronous, error, timeout, deadline, mode limits");
	return 0;
}
