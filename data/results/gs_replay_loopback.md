# gs_replay_loopback

- **Commit:** `424d18e` plus the uncommitted `gs/` tree it measures (committed together in the next commit)
- **Command:** `make gs-replay-results` (`PYTHONPATH=. python scripts/gs_replay_results.py`)
- **Tools:** g++ 15.2.0, CMake 4.2.3, Release build; Python 3.14.4; WSL2 Ubuntu 26.04, kernel 6.18.33.2
- **Input:** `data/synthetic/synthetic_seed2026_1024000SPS.cu8` (`make synthetic-iq`, seed 2026), 69,905,124 bytes.
  Synthetic; no real recording.

`gs-replay` sent the whole synthetic recording to 127.0.0.1, where a Python receiver checked each datagram's
sequence and hashed the payload. At real time, it achieved 1.00× (1,024,011 S/s over 34.133 s). At 5×, it achieved
5.00×. In both runs, all 68,266 datagrams arrived in order and the reassembled IQ was byte-identical to the file. The
`late_packets` column counts datagrams sent more than one period after their deadline: 222 at 1× (0.3%), 4,880 at 5×
(7%, where a period is only 100 µs). That is WSL scheduler jitter. Deadlines are absolute, so the average rate still
comes out exact, but late datagrams go out in short bursts. Flat-out reached 124× real time, and the Python receiver
lost about 11% of datagrams at about 250,000 per second. That is the measuring receiver's limit, not a sender fault,
and over the real 100 Mb/s link flat-out is capped at about 5.7× anyway (`docs/protocol.md`). Each run's final 740
bytes, less than one datagram, were reported and not sent. None of this measures the Ethernet link or the board;
that needs eth-core-v0.1.
