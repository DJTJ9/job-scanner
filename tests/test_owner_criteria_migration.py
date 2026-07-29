"""B3 — Migration Owner-Profil 9 → 25 Kriterien (WEIGHTS_CATALOG)."""
from jobscanner import scoring, storage


def _seed_owner_9(name="Tjark"):
    pid = storage.create_profile(name, {"skills": []})
    storage.save_criteria(pid, [dict(c, sort=i) for i, c in enumerate(storage.DEFAULT_CRITERIA)])
    return pid


def test_migriert_9_auf_25_und_erhaelt_remote_weight(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    pid = _seed_owner_9()
    # remote-Weight abweichend vom Default setzen
    crit = storage.list_criteria(pid)
    for c in crit:
        if c["key"] == "remote":
            c["weight"] = 1
    storage.save_criteria(pid, crit)

    migrated = storage.migrate_owner_criteria_to_weights()

    assert migrated == 1
    after = {c["key"]: c["weight"] for c in storage.list_criteria(pid)}
    assert len(after) == 25
    assert set(after) == {w["key"] for w in scoring.WEIGHTS_CATALOG}
    assert after["remote"] == 1                          # erhalten
    assert after["junior_level"] == 5                    # default_weight aus Katalog


def test_idempotent_und_laesst_member_25_unberuehrt(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    pid = _seed_owner_9()
    member = storage.create_profile("Member", {"skills": []})
    storage.save_criteria(member, [
        {"key": w["key"], "label": w["label"], "weight": w["default_weight"], "sort": i}
        for i, w in enumerate(scoring.WEIGHTS_CATALOG)])

    assert storage.migrate_owner_criteria_to_weights() == 1   # nur das 9er-Profil
    assert storage.migrate_owner_criteria_to_weights() == 0   # zweiter Lauf: nichts mehr
    assert len(storage.list_criteria(member)) == 25           # Member unangetastet
