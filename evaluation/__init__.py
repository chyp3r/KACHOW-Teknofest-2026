"""Deterministic, LLM-free evaluation of the system's non-model decision layer.

Everything under this package is measurement only -- it imports production code
but never modifies it, and it never calls a language model. That constraint is
what makes a run reproducible enough to calibrate a threshold against: an
LLM-as-judge harness would take hours against a local 9B model and would itself
be the noisiest term in the measurement.
"""
