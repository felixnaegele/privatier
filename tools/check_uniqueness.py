"""How many patients can be singled out by what stays in a folder? Prints counts only.

Someone who knows a patient's age, sex and date of surgery can recognise that patient, even without a name.

    python tools/check_uniqueness.py <folder>
"""

from __future__ import annotations

import sys
from pathlib import Path

from privatier.uniqueness import check_folder


def main(folder: Path) -> None:
    check = check_folder(folder)
    for table in [*check.tables, *([check.linked] if check.linked else [])]:
        if table.status == "could_not_check":
            print(f"{table.title}: COULD NOT CHECK ({table.reason}). This does not mean it is safe.")
        elif table.status == "nothing_to_compare":
            print(f"{table.title}: no sex, age or date columns recognised, so nothing to compare")
        else:
            print(f"{table.title}: {table.total} {table.unit}, using {', '.join(table.characteristics)}")
            print(f"   can be singled out: {table.singled_out} ({table.percent:.1f}%)")
            print(f"   in a group smaller than 5: {table.in_small_group} ({table.percent_small:.1f}%)")
    if check.other_files:
        print(f"{len(check.other_files)} file(s) are not tables and were not checked")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
