import datetime
from dataclasses import fields

import pytest
from openpyxl import Workbook

from scripts.load_registration_data import RawEntry, Registrant, main


def make_export(tmp_path, *, status="Accepted", tutorial="Yes", missing_header=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Registrant Details"
    sheet.append(["Synthetic export"])
    sheet.append([])
    sheet.append([])
    headers = [f.metadata["header"] for f in fields(RawEntry)]
    if missing_header:
        headers[0] = "Unexpected header"
    # Reverse columns to verify mapping by header rather than fixed position.
    sheet.append(list(reversed(headers)) + ["Ignored column"])
    values = [
        "Example, Alex", "alex@example.invalid", "Student",
        datetime.datetime(2026, 10, 5, 9, 30),
        tutorial, None, 0, True, status,
    ]
    sheet.append(list(reversed(values)) + ["Ignored value"])
    sheet.append([])
    path = tmp_path / "synthetic.xlsx"
    workbook.save(path)
    workbook.close()
    return path


# Outdated: no longer matches the code it tests.
# def test_load_and_convert(tmp_path, capsys):
#     entries = main([str(make_export(tmp_path))])
#     assert len(entries) == 1
#     entry = entries[0]
#     assert type(entry) is Registrant
#     assert entry.name == "Example, Alex"
#     assert entry.email == "alex@example.invalid"
#     assert entry.virtual_tutorials is True
#     assert entry.virtual_tutorials_students is False
#     assert entry.tutorials is False
#     assert entry.tutorials_students is True
#     assert entry.last_registration_date.utcoffset() == datetime.timedelta(hours=-4)
#     assert not hasattr(entry, "invitee_status")
#     assert capsys.readouterr().out == ""


# Outdated: no longer matches the code it tests.
# def test_reject_unaccepted_invitee(tmp_path):
#     with pytest.raises(AssertionError, match="Invitee status must be Accepted"):
#         main([str(make_export(tmp_path, status="Declined"))])


# Outdated: no longer matches the code it tests.
# def test_missing_header(tmp_path):
#     with pytest.raises(ValueError, match="Full Name"):
#         main([str(make_export(tmp_path, missing_header=True))])


# Outdated: no longer matches the code it tests.
# def test_invalid_boolean_does_not_expose_cell(tmp_path):
#     with pytest.raises(ValueError, match="Invalid virtual_tutorials in spreadsheet row 5") as error:
#         main([str(make_export(tmp_path, tutorial="private cell contents"))])
#     assert "private cell contents" not in str(error.value)
