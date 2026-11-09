"""Additive scheduler migration preserves verification ownership and old settings."""

from alembic import command
from sqlalchemy import select, text

from anki_generator.database.connection import migration_config, open_database
from anki_generator.database.entities import Card, Course, Run, Verification
from anki_generator.services.settings import get_settings


def test_task_migration_keeps_existing_run_references_and_identities(tmp_path):
    sessions = open_database(tmp_path)
    with sessions.begin() as session:
        course = Course(name="Migration course", deck_name="Migration")
        session.add(course)
        session.flush()
        card = Card(course_id=course.id, question="A preserved question")
        run = Run(course_id=course.id, status="completed")
        session.add_all([card, run])
        session.flush()
        verification = Verification(
            card_id=card.id, run_id=run.id, revision_number=1, stage="factual", verdict="pass"
        )
        session.add(verification)
        session.flush()
        run_id, card_id, guid, check_id = run.id, card.id, card.note_guid, verification.id
    engine = sessions.kw["bind"]
    for revision, operation in [
        ("0005_source_override_origin", command.downgrade),
        ("head", command.upgrade),
    ]:
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            operation(config, revision)
            assert (
                connection.scalar(
                    text("SELECT run_id FROM verifications WHERE id=:id"), {"id": check_id}
                )
                == run_id
            )
    with sessions() as session:
        assert session.get(Card, card_id).note_guid == guid
        assert session.get(Run, run_id).priority == 0
        assert session.get(Verification, check_id).run_id == run_id
        assert session.scalar(select(Run.status).where(Run.id == run_id)) == "completed"
    assert get_settings(sessions).tasks.max_concurrent_jobs == 2
    engine.dispose()
