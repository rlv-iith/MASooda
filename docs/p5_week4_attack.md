# P5 Week 4 attack demo summary

- Compared the same seeded 60-agent simulation for 120 s across no attack, undefended attack, and defended attack at 10 m, 25 m, and 50 m offsets; malicious id was 5 in every run.
- No attack produced 389 violation ticks with minimum robustness -6.76 m; undefended attack produced 334, 283, and 278 ticks at 10 m, 25 m, and 50 m.
- Defence produced 277, 297, and 293 violation ticks at those offsets; at 25 m, minimum robustness after 50 s was -6.76 m (none), -7.53 m (undefended), and -7.69 m (defended).
- Defence dropped 3,010, 3,241, and 3,417 reports at 10 m, 25 m, and 50 m, with zero honest reports wrongly dropped.
- Mean reported-position error seen by the malicious agent's neighbours rose with offset; these runs show no elimination of safety violations, so the outcomes are an empirical comparison rather than a safety guarantee.
