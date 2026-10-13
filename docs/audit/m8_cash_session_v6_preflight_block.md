# M8 cash-session v6 preflight block

The v6 session was frozen, but preflight blocked before outcome computation. The run intent's independent-audit `source_sha256` was set to the implementation source hash, while the installed preflight contract requires it to identify the referenced audit-recipe evidence file. The v6 session and its files remain unchanged and no attempt was launched. v7 will bind both identities separately: intent hash to the recipe file and the recipe's internal source hash to the audited implementation.
