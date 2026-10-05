"""Indian number-plate normalisation — pure-function unit tests.

No fixtures, no database, no network: every assertion calls app.anpr directly.
(The suite-wide conftest still requires Postgres to collect, so these were also
verified by executing the pure functions standalone.)

Covered formats:
  standard  SS + RTO(1-2 digits) + series(1-3 letters) + 4 digits
            incl. the older single-letter series "MH 1 A 1234"
            and Delhi-style 3-letter series "DL 8C AF 5030"
  bh        Bharat series  YY + "BH" + 4 digits + 1-2 letters (no state code)
"""

from app.anpr import extract_plate_from_lines, normalize_plate, normalize_plate_detail

# ---------------- standard format ----------------


def test_clean_standard_reads_pass_through():
    assert normalize_plate("MH12AB1234") == "MH12AB1234"
    assert normalize_plate("MH 12 AB 1234") == "MH12AB1234"
    assert normalize_plate("KA01AB1234") == "KA01AB1234"
    assert normalize_plate("DL8CAF5030") == "DL8CAF5030"      # 1-digit RTO, 3-letter series
    assert normalize_plate("DL13CAF5030") == "DL13CAF5030"    # 2-digit RTO, 3-letter series


def test_single_digit_rto_and_older_single_letter_series():
    # older/short shapes: SS N L NNNN and SS NN L NNNN
    assert normalize_plate("MH 1 A 1234") == "MH1A1234"
    assert normalize_plate("MH1AB1234") == "MH1AB1234"
    assert normalize_plate("MH 12 A 1234") == "MH12A1234"


def test_lowercase_and_mixed_case():
    assert normalize_plate("mh12ab1234") == "MH12AB1234"
    assert normalize_plate("Mh-12-aB-1234") == "MH12AB1234"
    assert normalize_plate("mho2fx266o") == "MH02FX2660"


# ---------------- spacing / punctuation / sticker noise ----------------


def test_separator_and_sticker_noise():
    assert normalize_plate("MH-12-AB-1234") == "MH12AB1234"
    assert normalize_plate("MH.12.AB.1234") == "MH12AB1234"
    assert normalize_plate("MH  12   AB  1234") == "MH12AB1234"
    assert normalize_plate("IND MH12AB1234") == "MH12AB1234"
    assert normalize_plate("IND MH 12 AB 1234") == "MH12AB1234"
    assert normalize_plate("INDMH12AB1234") == "MH12AB1234"


def test_surrounding_junk_is_discarded():
    assert normalize_plate("***MH12AB1234***") == "MH12AB1234"
    assert normalize_plate("MH12AB1234 GATE-3") == "MH12AB1234"
    assert normalize_plate("truck at gate MH12AB1234") == "MH12AB1234"
    assert normalize_plate("plate: MH-12-AB-1234 (inbound)") == "MH12AB1234"
    assert normalize_plate("MH 12 AB 1234 parked") == "MH12AB1234"


# ---------------- positional confusable repair ----------------


def test_confusable_repair_is_position_aware():
    # the real production failure: Rekognition read MH02FX2660 as "MHO2FX266O"
    assert normalize_plate("MHO2FX266O") == "MH02FX2660"
    assert normalize_plate("MHO2FX2660") == "MH02FX2660"
    assert normalize_plate("MHO2FXZ66O") == "MH02FX2660"
    # letters are only coerced to digits where the layout demands digits:
    # "FX" sits in the letter series above and is left alone.
    assert normalize_plate("MHI2AB1234") == "MH12AB1234"   # I->1 inside the RTO
    assert normalize_plate("0D02AB1234") == "OD02AB1234"   # 0->O inside the state code


def test_fewest_repairs_wins():
    # "MH1ZAB1234" parses with ZERO repairs as a Delhi-style 3-letter series
    # (MH | 1 | ZAB | 1234), so that reading beats coercing Z->2 in the RTO.
    assert normalize_plate("MH1ZAB1234") == "MH1ZAB1234"
    assert normalize_plate_detail("MH1ZAB1234")["fixes"] == []


def test_fixes_audit_trail_standard():
    d = normalize_plate_detail("MHO2FX266O")
    assert d["raw"] == "MHO2FX266O"          # raw read never mutated
    assert d["normalised"] == "MH02FX2660"
    assert d["format"] == "standard"
    assert d["state"] == "MH"
    assert d["fixes"] == ["pos2 O->0", "pos9 O->0"]


def test_no_fixes_when_read_is_already_clean():
    d = normalize_plate_detail("MH 12 AB 1234")
    assert d["raw"] == "MH 12 AB 1234"
    assert d["candidate"] == "MH12AB1234"
    assert d["normalised"] == "MH12AB1234"
    assert d["fixes"] == []


# ---------------- BH (Bharat) series ----------------


def test_bh_series():
    assert normalize_plate("22BH1234AA") == "22BH1234AA"
    assert normalize_plate("22 BH 1234 AA") == "22BH1234AA"
    assert normalize_plate("23-BH-5678-A") == "23BH5678A"   # 1-letter tail
    assert normalize_plate("IND 22BH1234AA") == "22BH1234AA"
    d = normalize_plate_detail("22BH1234AA")
    assert d["format"] == "bh"
    assert d["state"] is None                # BH plates carry no state code
    assert d["fixes"] == []


def test_bh_series_confusable_repair_in_literal_bh():
    # "B" misread as "8" in a position where the format demands the letter B
    d = normalize_plate_detail("22 8H 1234 AA")
    assert d["raw"] == "22 8H 1234 AA"
    assert d["normalised"] == "22BH1234AA"
    assert d["format"] == "bh"
    assert d["fixes"] == ["pos2 8->B"]
    # and the year digits repaired the other way: "ZZ" -> "22"
    d2 = normalize_plate_detail("ZZBH1234AA")
    assert d2["normalised"] == "22BH1234AA"
    assert d2["fixes"] == ["pos0 Z->2", "pos1 Z->2"]


def test_bh_is_not_rejected_by_state_code_validation():
    # "22" is not a state code; BH plates must bypass that check entirely
    assert normalize_plate("22BH1234AA") is not None
    # ...while a standard-shaped plate with a bogus state code is still rejected
    assert normalize_plate("XY12AB1234") is None


# ---------------- rejection: None is the correct answer ----------------


def test_rejects_non_plates():
    assert normalize_plate("9876543210") is None          # phone number
    assert normalize_plate("+91 98765 43210") is None     # phone number with country code
    assert normalize_plate("12/06/2024") is None          # date
    assert normalize_plate("2024-10-06") is None          # ISO date
    assert normalize_plate("NO VEHICLES HERE") is None    # random words
    assert normalize_plate("SPEED LIMIT 30") is None
    assert normalize_plate("SPEEDLIMIT30") is None
    assert normalize_plate("HELLO") is None
    assert normalize_plate("DESIGNO") is None             # a real DetectText line
    assert normalize_plate("") is None
    assert normalize_plate(None) is None


def test_rejects_wrong_state_code_and_wrong_shape():
    assert normalize_plate("XY12AB1234") is None          # XY is not an Indian state code
    assert normalize_plate("MH12AB12") is None            # 2-digit tail
    assert normalize_plate("MH12AB12345") is None         # 5-digit tail
    assert normalize_plate("MH12AB1234X") is None         # letter after the 4-digit tail
    assert normalize_plate("MHAB1234") is None            # no RTO digits
    assert normalize_plate("22XX1234AA") is None          # BH shape, wrong literal
    assert normalize_plate("MH12ABCD1234") is None        # 4-letter series


def test_three_letter_series_must_be_read_exactly():
    # The Delhi-style 3-letter series overlaps the 1-2 letter layouts' character
    # classes, so it is only accepted with zero repairs. Otherwise ordinary text
    # and over-long reads coerce into plausible-looking plates.
    assert normalize_plate("DL8CAF5030") == "DL8CAF5030"     # exact read: accepted
    assert normalize_plate("DL GATE 1234") is None           # would be "DL6ATE1234"
    assert normalize_plate("DL8C4F5030") is None             # would be "DL8CAF5030"


def test_detail_returns_none_for_rejections():
    assert normalize_plate_detail("9876543210") is None
    assert normalize_plate_detail("JUST A WALL") is None


# ---------------- OCR line scanning (uses the same normaliser) ----------------


def test_extract_plate_from_lines_handles_bh_and_sticker_lines():
    assert extract_plate_from_lines(
        [{"text": "IND 22 BH 1234 AA", "confidence": 80.0}]
    ) == ("22BH1234AA", 80.0)
    assert extract_plate_from_lines(
        [{"text": "GATE 2 ENTRY", "confidence": 99.0}, {"text": "MHO2FX266O", "confidence": 61.0}]
    ) == ("MH02FX2660", 61.0)
    assert extract_plate_from_lines([{"text": "NO PARKING", "confidence": 99.0}]) == (None, None)
