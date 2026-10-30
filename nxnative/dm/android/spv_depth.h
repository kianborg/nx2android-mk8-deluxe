// Runtime GL (-w..w) to Vulkan (0..w) clip-depth conversion, without retranslating shaders.
#pragma once
#include <stdint.h>

// Returns an allocated module, or NULL for malformed/unsupported input. Rewrites
// vertex/tess-evaluation returns or geometry emissions; leaves other outputs intact.
uint32_t *vk_spv_depth_remap(const uint32_t *words, uint32_t count, uint32_t *out_count);
