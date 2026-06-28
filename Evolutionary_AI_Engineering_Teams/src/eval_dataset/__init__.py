"""Eval-case dataset: the labeled-failure store that powers the feedback flywheel.

Production negative sentiment -> capture an EvalCase (needs_label) -> a human
supplies the expected output (labeled) -> evolution re-runs against the enriched
dataset, graded reference-against the expected output.
"""
