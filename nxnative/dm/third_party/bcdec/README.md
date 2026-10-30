# bcdec

Unmodified `bcdec.h` v0.985 from https://github.com/iOrange/bcdec,
commit `80859ed3b7afb1c527a2a99d70c61457bea72d0c`.

Used under the MIT option in LICENSE. The Android CPU fallback calls it through
`dm/gfx/tex/nvn_bc.c`. BC4/BC5 precise decoding is enabled for signed formats.
Native BC uploads are retained on devices supporting textureCompressionBC.
