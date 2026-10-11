from rangemusique.textutil import (
    clean_folder_name, main_artist, parse_filename, safe_name, similarity, title_key,
)


def test_parse_artist_title():
    assert parse_filename("Berlin - Take My Breath Away") == {
        "artist": "Berlin", "title": "Take My Breath Away"}


def test_parse_track_title():
    assert parse_filename("07 - Take My Breath Away") == {
        "track": 7, "title": "Take My Breath Away"}
    assert parse_filename("07. Take My Breath Away")["track"] == 7
    assert parse_filename("07 Take My Breath Away")["track"] == 7


def test_parse_full():
    r = parse_filename("03 - Berlin - Top Gun - Take My Breath Away")
    assert r == {"track": 3, "artist": "Berlin", "album": "Top Gun",
                 "title": "Take My Breath Away"}


def test_parse_keeps_numbers_in_titles():
    assert parse_filename("99 Luftballons") == {"title": "99 Luftballons"}
    assert parse_filename("Nena - 99 Luftballons") == {"artist": "Nena",
                                                       "title": "99 Luftballons"}


def test_parse_removes_junk():
    r = parse_filename("Berlin_-_Take_My_Breath_Away_(Official_Video)_[HQ]")
    assert r == {"artist": "Berlin", "title": "Take My Breath Away"}


def test_parse_disc_track():
    r = parse_filename("2-05 Some Song")
    assert r["disc"] == 2 and r["track"] == 5 and r["title"] == "Some Song"


def test_safe_name():
    assert safe_name("AC/DC") == "AC-DC"
    assert safe_name("Mission: Impossible?") == "Mission - Impossible"
    assert safe_name("CON") == "_CON"
    assert safe_name("  ...  ") == "Inconnu"
    assert safe_name("Album...") == "Album"
    assert len(safe_name("x" * 300)) == 80


def test_similarity_and_artists():
    assert similarity("Take My Breath Away", "take my breath away") == 1.0
    assert similarity("Take My Breath Away (Love Theme from Top Gun)",
                      "Take My Breath Away") > 0.9
    assert similarity("Beyoncé", "Beyonce") == 1.0
    assert similarity("The Beatles", "Beatles") == 1.0
    assert main_artist("David Guetta feat. Sia") == "David Guetta"
    assert main_artist("David Guetta (ft. Sia)") == "David Guetta"
    assert main_artist("Simon & Garfunkel") == "Simon & Garfunkel"


def test_title_key():
    assert title_key("Heroes (2017 Remaster)") == title_key("Heroes")
    assert title_key("Heroes - Remastered 1999") == title_key("Heroes")
    assert title_key("Heroes (Live)") != title_key("Heroes")


def test_clean_folder_name():
    assert clean_folder_name("Berlin - Top Gun (1986) [FLAC]") == "Berlin - Top Gun"
