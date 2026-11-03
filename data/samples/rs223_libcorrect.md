# rs223_libcorrect.json

Three RS(255,223) codewords as hex, produced by libcorrect as vendored in SatDump 1.2.2 (commit `7aef0fe`,
`src-core/libs/correct/`), using `correct_reed_solomon_create(0x187, 112, 11, 32)`, the call in
`src-core/common/codings/reedsolomon/reedsolomon.cpp:32`.

- Word 0: all-zero message.
- Words 1 and 2: `x = x * 1103515245 + 12345`, seeded with 12345, message byte = `(x >> 16) & 0xff`.

Built with gcc from only the `reed-solomon/` sources. It gives `model/rs.py` a check independent of its own encoder.
