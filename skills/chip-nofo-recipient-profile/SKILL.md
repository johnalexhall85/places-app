---
name: chip-nofo-recipient-profile
description: Build a branded recipient profile report (Word + Excel) for a CDC funding opportunity (NOFO) from CHIP's USAspending and TAGGS data. Use when the user asks for a recipient profile, recipient dossier, recipient report, grantee list, or "who got funded" for a CDC NOFO / funding opportunity number such as CDC-RFA-PS21-2102 or PS21-2102, with or without sub-awardees. Requires the CHIP by Public Data Observatory connector.
---

# CDC NOFO Recipient Profile (CHIP)

This skill produces two files for a CDC funding opportunity:

- `<FON>_Recipient_Profile.docx`: a Public Data Observatory–branded report. It has an executive summary, fiscal-year obligations, and one profile per recipient.
- `<FON>_Recipient_Profile.xlsx`: the same data in sortable sheets.

The data comes from the CHIP MCP connector ("CHIP by Public Data Observatory"). `scripts/render.py` writes the files. **You never type data into the files yourself.** Every number comes from the dataset, and the renderer composes it.

## 1. Get the two inputs

- **The funding opportunity number.** Any form is accepted: `CDC-RFA-PS21-2102`, `PS21-2102`, `ps21 2102`.
- **Whether to include sub-awardees.** If the user didn't say, ask one short question ("Include sub-awardees? They add a section and two sheets."). Don't ask anything else unless the NOFO is ambiguous.

## 2. Check the NOFO with the connector

Call `get_nofo_overview` with `nofo` and `include_subawards`.

- **No match:** the error lists suggestions. Show them and ask which one the user meant.
- **Not a CDC NOFO:** say that only CDC funding opportunities are supported for now, and stop.
- **Match:** note `dataset_url`, the recipient count, the total, and the data-through dates from `sources`.

## 3. Download the dataset in the code sandbox

```bash
curl -sSL --compressed --fail "<dataset_url>" -o /tmp/nofo_dataset.json
python3 -c "import json;d=json.load(open('/tmp/nofo_dataset.json'));print(d['schema_version'],len(d['recipients']))"
```

Use the URL exactly as returned. The script expects `schema_version` to be `chip.nofo_recipient_profile.v1`.

If the download fails because of a network or proxy error, the sandbox can't reach CHIP. Don't rebuild the dataset from tool calls. Tell the user:

> Claude's code sandbox needs network access to the CHIP host in the dataset link (`mcp.publicdataobservatory.org`, or `chip-beta.publicdataobservatory.org` for the staging tryout). In claude.ai, open **Settings → Capabilities → Code execution and file creation**, allow network egress, and add that domain to the allowed domains (or allow all domains). Then ask again.

Meanwhile, offer a short in-chat summary built from `get_nofo_overview`, plus `list_nofo_recipients` for NOFOs with 100 or fewer recipients.

## 4. Render

```bash
pip install --quiet python-docx openpyxl matplotlib 2>/dev/null || true
python3 <skill_dir>/scripts/render.py --dataset /tmp/nofo_dataset.json --out /mnt/user-data/outputs
```

- `<skill_dir>` is the folder that contains this `SKILL.md`.
- If `/mnt/user-data/outputs` doesn't exist, use any writable folder, then share the files.
- Add `--title "<program title>"` only if the user gave the program's official title. Otherwise the renderer uses the assistance-listing title.
- **Optional `--narrative narrative.json`** with `{"context": ["paragraph", ...]}`. The paragraphs are printed under "Context" in the executive summary. Use them only for context the user provided, or that you can cite (for example, the NOFO's purpose from grants.gov, with the link). Never put a dollar figure or count in the narrative that is not in the dataset.

The script prints the paths it wrote and a JSON summary. If it exits non-zero, show the error. Don't hand-build the documents.

## 5. Report back

Share both files. Add a reply of five lines or fewer covering:

- the recipient count;
- the total obligated and its fiscal-year range;
- any incomplete fiscal year;
- whether sub-awardees are included;
- the sources line from the dataset (for example "Source: USAspending.gov · … · CHIP build N").

## Rules

- Cite numbers with the dataset's `sources[].citation`. State data-through dates. Say when a fiscal year is not complete.
- Sub-award amounts are reported by prime recipients and are **not additional federal funding**. Never add them to prime obligations.
- "Other HHS awards" are TAGGS awards with the same UEI. They are not a complete federal portfolio.
- Don't rank recipients by merit, and don't call funding good, bad, wasteful, or at risk. Report amounts, periods, and sources.
- A missing value is missing, not zero.

See `references/report_spec.md` for the full layout.
