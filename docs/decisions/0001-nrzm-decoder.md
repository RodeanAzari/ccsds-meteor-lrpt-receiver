# 0001: Add an NRZ-M decoder after Viterbi

## Context

SatDump 1.2.2's `meteor_m2-x_lrpt` pipeline sets `"nrzm": true`. The architecture in CLAUDE.md §3 has no differential
decoder. See `docs/signal-spec.md`.

## Options considered

1. **Hardware block between Viterbi and the ASM check.** Same position as SatDump. One flip-flop and one XOR.
2. **Follow CLAUDE.md §3 unchanged.** Rejected: the post-Viterbi ASM would never match.

## Decision

Option 1. The encoded-ASM correlator also uses the NRZ-M-encoded pattern, correlating on absolute value because the two
NRZ-M polarities are complements.

## Consequences

- 180° carrier ambiguity needs no correction, so the phase search can shrink to {0°, 90°} × swap × shift, pending
  confirmation on a recording.
- A Viterbi output error becomes two adjacent errors after NRZ-M decoding, so post-Viterbi BER rises. BER campaigns have
  to measure at a labelled point: before or after NRZ-M.

## Measured evidence

`scripts/verify_signal_spec.py` shows the NRZ-M encoded ASM matches SatDump's constant on the last 52 symbols. There is
no measurement on a real signal yet: `[TBD]`.
