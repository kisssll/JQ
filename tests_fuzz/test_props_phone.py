"""Свойства нормализации телефона (app/schemas/user.py)."""
import re

from hypothesis import given, seed, strategies as st

from app.schemas.user import PHONE_RE, try_normalize_phone
from tests_fuzz.profile import SEED, props

ten = st.text(alphabet="0123456789", min_size=10, max_size=10)


def _spelled(d: str, variant: int, sep: str) -> str:
    a, b, c, e = d[:3], d[3:6], d[6:8], d[8:]
    prefix = ["+7", "8", "7", "+7 ", "8 "][variant]
    return f"{prefix}{sep}({a}){sep}{b}{sep}{c}{sep}{e}" if sep != "|" else f"{prefix}{d}"


@seed(SEED)
@props()
@given(d=ten, v1=st.integers(0, 4), v2=st.integers(0, 4),
       s1=st.sampled_from([" ", "-", ".", "", " ", "\t"]),
       s2=st.sampled_from([" ", "-", ".", "", "|"]))
def test_every_spelling_of_one_number_gives_one_record(d, v1, v2, s1, s2):
    """«+7 (912) 345-67-89», «8 912 345 67 89», «79123456789» — один человек."""
    a = try_normalize_phone(_spelled(d, v1, s1))
    b = try_normalize_phone(_spelled(d, v2, s2))
    assert a == b == "+7" + d


@seed(SEED)
@props()
@given(raw=st.text(max_size=60))
def test_garbage_never_raises_and_result_is_canonical(raw):
    """На мусоре — отказ (None), а не исключение; согласие — только каноническая
    ASCII-форма, иначе один номер получил бы две записи."""
    out = try_normalize_phone(raw)
    assert out is None or re.fullmatch(r"\+7[0-9]{10}", out), repr(out)
    if out is not None:
        assert try_normalize_phone(out) == out  # идемпотентность
        assert PHONE_RE.match(out)


@seed(SEED)
@props()
@given(raw=st.one_of(st.none(), st.binary().map(lambda b: b.decode("latin-1")), st.text()))
def test_none_and_binary_noise_are_refusals(raw):
    try_normalize_phone(raw)  # не должно бросить


@seed(SEED)
@props()
@given(raw=st.text(alphabet=st.characters(categories=["Nd"]), min_size=10, max_size=12))
def test_non_ascii_digits_are_not_a_phone(raw):
    """Арабо-индийские и прочие Unicode-цифры не должны давать «валидный» номер:
    это вторая запись для того же человека, которую не найдёт поиск по ASCII."""
    out = try_normalize_phone("+7" + raw)
    assert out is None or out.isascii()
