import pandas as pd

import export
from schemas import JOB_FIELDS, LOGIN_FIELDS, PREMIUM_FIELDS, PRIVATE_FIELDS


def test_private_fields_are_real_job_fields():
    """public_view silently skips names that match no column — a typo in
    PRIVATE_FIELDS would silently LEAK that column to the public dataset."""
    assert set(PRIVATE_FIELDS) <= set(JOB_FIELDS)
    assert not set(LOGIN_FIELDS) & set(PREMIUM_FIELDS)


def test_public_view_drops_exactly_the_private_fields():
    df = pd.DataFrame([{f: "x" for f in JOB_FIELDS}])
    public = export.public_view(df)
    assert set(public.columns) == set(JOB_FIELDS) - set(PRIVATE_FIELDS)


def test_public_view_tolerates_missing_columns():
    df = pd.DataFrame([{"job_id": "1", "job_title": "DS"}])
    assert list(export.public_view(df).columns) == ["job_id", "job_title"]
