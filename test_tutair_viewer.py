import shutil
import tempfile
import unittest
from io import BytesIO
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

import tutair_viewer as viewer_module
from tutair_intake import TutairCapture, save_capture, save_source_content, with_source_content_fields
from tutair_process import process_capture
from tutair_viewer import (
    TutorEnvStatus,
    TutorProviderError,
    build_tutor_messages,
    call_configured_ai_provider,
    find_processed_notes,
    load_tutair_env,
    parse_processed_note,
    render_home,
    render_tutor,
    sanitize_openai_log_text,
    set_env_from_dotenv_line,
    tutor_context,
    tutor_mode_instruction,
)


class TestTutairViewer(unittest.TestCase):
    def test_find_processed_notes_reads_processed_folder(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-viewer-"))
        try:
            capture_path = make_processed_note(temp_dir)
            notes = find_processed_notes(temp_dir)

            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0].subject, "Science")
            self.assertEqual(notes[0].topic, "Cell division")
            self.assertIn("Tiny Summary", notes[0].sections)
            self.assertIn("processed", str(capture_path.parent))
        finally:
            shutil.rmtree(temp_dir)

    def test_parse_processed_note_extracts_sections(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-viewer-"))
        try:
            processed_path = make_processed_note(temp_dir)
            note = parse_processed_note(processed_path, temp_dir)

            self.assertEqual(note.exam_board_status, "unconfirmed")
            self.assertIn("Mitosis makes new body cells.", note.sections["Tiny Summary"])
            self.assertIn("What This Means", note.sections)
        finally:
            shutil.rmtree(temp_dir)

    def test_render_home_has_empty_state(self):
        html = render_home([])

        self.assertIn("No processed notes yet", html)
        self.assertIn("Team Inbox/TutAIR/YYYY/MM/processed/", html)

    def test_render_home_lists_note_subject_and_topic(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-viewer-"))
        try:
            make_processed_note(temp_dir)
            html = render_home(find_processed_notes(temp_dir))

            self.assertIn("Science", html)
            self.assertIn("Cell division", html)
            self.assertIn("Exam-Style Questions", html)
            self.assertIn("Flashcards", html)
        finally:
            shutil.rmtree(temp_dir)

    def test_render_home_includes_interactive_dashboard_hooks(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-viewer-"))
        try:
            make_processed_note(temp_dir)
            html = render_home(find_processed_notes(temp_dir))

            self.assertIn('data-action="flashcards"', html)
            self.assertIn('data-action="quiz"', html)
            self.assertIn('data-action="read-aloud"', html)
            self.assertIn('data-action="focus"', html)
            self.assertIn('data-action="mark-reviewed"', html)
            self.assertIn('data-action="save-topic"', html)
            self.assertIn("localStorage", html)
            self.assertIn("speechSynthesis", html)
            self.assertIn("practice-view", html)
        finally:
            shutil.rmtree(temp_dir)

    def test_render_home_includes_onboarding_and_personal_dashboard_hooks(self):
        html = render_home([])

        self.assertIn('id="profile-app"', html)
        self.assertIn("Remember me on this device", html)
        self.assertIn("Create Account", html)
        self.assertIn("Forgot Password?", html)
        self.assertIn("Smarter Revision", html)
        self.assertIn("setup-progress", html)
        self.assertIn("auth-benefits", html)
        self.assertIn("continue-panel", html)
        self.assertIn("Year 9", html)
        self.assertIn("Year 10", html)
        self.assertIn("Year 11", html)
        self.assertIn("Skip For Now", html)
        self.assertIn("Start Today's Mission", html)
        self.assertIn("subject-dashboard-grid", html)
        self.assertIn("dashboard-stats", html)
        self.assertIn("data-board-button", html)
        self.assertIn("data-profile-action=\"edit-subjects\"", html)
        self.assertIn("tutair.viewer.profile", html)

    def test_profile_flow_hides_inactive_shell_and_locks_onboarding_scroll(self):
        html = render_home([])

        self.assertIn("[hidden]", html)
        self.assertIn("display: none !important", html)
        self.assertIn("app.style.display = \"none\"", html)
        self.assertIn("document.body.dataset.profileView = view", html)
        self.assertIn('body[data-profile-view="onboarding"]', html)
        self.assertIn("overflow: hidden", html)
        self.assertIn("max-height: 100vh", html)

    def test_settings_logout_clears_profile_session_and_returns_to_login(self):
        html = render_home([])

        self.assertIn("function renderSettings()", html)
        self.assertIn("Account settings", html)
        self.assertIn('data-profile-action="logout-confirm"', html)
        self.assertIn("Are you sure you want to log out?", html)
        self.assertIn('data-profile-action="logout"', html)
        self.assertIn("function logoutPrototypeUser()", html)
        self.assertIn("localStorage.removeItem(profileKey)", html)
        self.assertIn("sessionStorage.removeItem(sessionKey)", html)
        self.assertIn('renderLogin("login")', html)
        self.assertIn("Remember Me", html)

    def test_subject_selection_uses_card_highlight_without_floating_ticks(self):
        html = render_home([])

        self.assertIn("subject-choice", html)
        self.assertIn("data-subject=", html)
        self.assertIn("choice-card subject-choice", html)
        self.assertNotIn("floating tick", html.lower())
        self.assertNotIn("purple tick", html.lower())

    def test_subject_card_click_sets_current_subject_to_maths(self):
        html = render_home([])

        self.assertIn('data-subject-open="${subject.id}"', html)
        self.assertIn("function renderSubjectPage(subjectId)", html)
        self.assertIn("function setCurrentSubject(subjectId)", html)
        self.assertIn("profile.currentSubject = subject.name", html)
        self.assertIn("profile.currentTopic = \"\"", html)
        self.assertIn("Number", html)
        self.assertIn("Algebra", html)
        self.assertIn("Geometry & Measures", html)
        self.assertIn("Pythagoras", html)
        self.assertIn("Simultaneous Equations", html)

    def test_subject_card_click_sets_current_subject_to_biology(self):
        html = render_home([])

        self.assertIn('data-subject-open="${subject.id}"', html)
        self.assertIn("return renderSubjectPage(target?.dataset.subjectOpen", html)
        self.assertIn("profile.currentSubjectId = subject.id", html)

    def test_tutor_subject_route_does_not_default_maths_to_cell_division(self):
        html = render_tutor([], requested_subject="maths")

        self.assertIn("<dd>Maths</dd>", html)
        self.assertIn("<dd>Topic not selected yet</dd>", html)
        self.assertIn('"subject": "Maths"', html)
        self.assertIn('"topic": "Topic not selected yet"', html)
        self.assertNotIn("Current Topic: Cell division", html)
        self.assertNotIn('"topic": "Cell division"', html)

    def test_render_home_embeds_flashcard_and_quiz_data(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-viewer-"))
        try:
            make_processed_note(temp_dir)
            html = render_home(find_processed_notes(temp_dir))

            self.assertIn('"flashcards"', html)
            self.assertIn('"questions"', html)
            self.assertIn("What topic is this note about?", html)
            self.assertIn("What is the main idea in this source?", html)
        finally:
            shutil.rmtree(temp_dir)

    def test_render_tutor_includes_chat_interface_and_prompt_hooks(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-viewer-"))
        try:
            note_path = make_processed_note(temp_dir)
            notes = find_processed_notes(temp_dir)
            html = render_tutor(notes, notes[0].id)

            self.assertIn("TutAIR Coach", html)
            self.assertIn("data-learning-stage", html)
            self.assertIn("data-lesson-xp", html)
            self.assertIn("data-lesson-progress", html)
            self.assertIn("New Chat", html)
            self.assertIn("Clear Chat", html)
            self.assertIn("data-chat-history", html)
            self.assertIn("data-tutor-form", html)
            self.assertIn("data-tutor-send", html)
            self.assertIn("data-prompt=", html)
            self.assertIn("data-tutor-mode=\"exam-question\"", html)
            self.assertIn("Start Lesson", html)
            self.assertIn("Create Flashcards", html)
            self.assertIn("Mission", html)
            self.assertIn("data-tutor-save-panel", html)
            self.assertIn("data-tutor-error", html)
            self.assertIn("/api/tutor/chat", html)
            self.assertIn("tutair.viewer.tutor.history", html)
            self.assertIn("tutair.viewer.tutor.session", html)
            self.assertIn("tutair.viewer.tutor.savedFlashcards", html)
            self.assertIn("Cell division", html)
            self.assertIn(str(note_path.name), notes[0].path.name)
        finally:
            shutil.rmtree(temp_dir)

    def test_tutor_context_personalises_with_note_and_profile(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-viewer-"))
        try:
            make_processed_note(temp_dir)
            note = find_processed_notes(temp_dir)[0]
            context = tutor_context(
                note,
                {
                    "name": "Sam",
                    "yearGroup": "Year 11",
                    "subjects": ["science", "computer-science"],
                    "examBoards": {"science": "AQA"},
                },
            )

            self.assertEqual(context["student_name"], "Sam")
            self.assertEqual(context["year_group"], "Year 11")
            self.assertEqual(context["selected_subjects"], "Science, Computer Science")
            self.assertEqual(context["subject"], "Science")
            self.assertEqual(context["exam_board"], "AQA")
            self.assertEqual(context["topic"], "Cell division")
        finally:
            shutil.rmtree(temp_dir)

    def test_tutor_context_uses_clicked_subject_without_selected_topic(self):
        context = tutor_context(
            None,
            {
                "name": "Sam",
                "yearGroup": "Year 11",
                "subjects": ["maths", "biology"],
                "examBoards": {"maths": "Edexcel"},
                "currentSubject": "Maths",
            },
        )

        self.assertEqual(context["student_name"], "Sam")
        self.assertEqual(context["year_group"], "Year 11")
        self.assertEqual(context["selected_subjects"], "Maths, Biology")
        self.assertEqual(context["subject"], "Maths")
        self.assertEqual(context["topic"], "Topic not selected yet")
        self.assertEqual(context["exam_board"], "Edexcel")

    def test_tutor_messages_for_maths_do_not_use_cell_division_fallback(self):
        context = tutor_context(
            None,
            {
                "name": "Sam",
                "yearGroup": "Year 10",
                "subjects": ["maths"],
                "currentSubject": "Maths",
            },
        )
        messages = build_tutor_messages("Help me choose a topic.", [], context, None, "lesson")

        self.assertIn("Current Subject: Maths", messages[0]["content"])
        self.assertIn("Current Topic: Topic not selected yet", messages[0]["content"])
        self.assertNotIn("Cell division", messages[0]["content"])

    def test_build_tutor_messages_includes_learning_context(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-viewer-"))
        try:
            make_processed_note(temp_dir)
            note = find_processed_notes(temp_dir)[0]
            context = tutor_context(note, {"name": "Sam", "yearGroup": "Year 10", "subjects": ["science"]})
            messages = build_tutor_messages(
                "Explain mitosis.",
                [{"role": "user", "content": "I am stuck."}],
                context,
                note,
                "revision-notes",
            )

            self.assertEqual(messages[-1]["content"], "Explain mitosis.")
            self.assertIn("Name: Sam", messages[0]["content"])
            self.assertIn("Year Group: Year 10", messages[0]["content"])
            self.assertIn("Selected Subjects: Science", messages[0]["content"])
            self.assertIn("Subject: Science", messages[0]["content"])
            self.assertIn("Current Topic: Cell division", messages[0]["content"])
            self.assertIn("Mitosis makes new body cells", messages[0]["content"])
            self.assertIn("Return strict JSON only", messages[0]["content"])
            self.assertIn('"quiz"', messages[0]["content"])
            self.assertIn('"mission_complete"', messages[0]["content"])
        finally:
            shutil.rmtree(temp_dir)

    def test_tutor_mode_instruction_supports_exam_marking_and_quiz(self):
        self.assertIn("score", tutor_mode_instruction("exam-answer"))
        self.assertIn("mini multiple-choice", tutor_mode_instruction("quiz"))
        self.assertIn("front, back, and difficulty", tutor_mode_instruction("flashcards"))
        self.assertIn("Start at step 1", tutor_mode_instruction("lesson"))

    def test_tutor_script_supports_enter_send_quick_actions_and_flashcard_save(self):
        html = render_tutor([])

        self.assertIn('event.key === "Enter" && !event.shiftKey', html)
        self.assertIn("form.requestSubmit()", html)
        self.assertIn("renderLessonStage", html)
        self.assertIn("parseLessonReply", html)
        self.assertIn("applyLessonReward", html)
        self.assertIn("lessonStatePrefix", html)
        self.assertIn("data-quiz-choice", html)
        self.assertIn('mode === "exam-question"', html)
        self.assertIn('mode === "exam-answer"', html)
        self.assertIn("saveLatestFlashcards", html)
        self.assertIn("Flashcards saved locally", html)

    def test_tutor_learning_engine_visual_hooks_are_present(self):
        html = render_tutor([])

        self.assertIn("lesson-status", html)
        self.assertIn("xp-orb", html)
        self.assertIn("robot-face", html)
        self.assertIn("mission-complete", html)
        self.assertIn("confetti", html)
        self.assertIn("badge-row", html)
        self.assertIn("levelPop", html)

    def test_tutor_json_is_rendered_as_cards_not_raw_history(self):
        html = render_tutor([])

        self.assertIn("friendlyHistoryContent", html)
        self.assertIn("looksLikeLessonJson", html)
        self.assertIn("Lesson card ready.", html)
        self.assertIn("<h3>Quick Learn</h3>", html)
        self.assertIn("Think of it like", html)
        self.assertIn("Important fact", html)
        self.assertIn("quiz-choice-grid", html)

    def test_tutor_malformed_json_uses_friendly_fallback(self):
        html = render_tutor([])

        self.assertIn("TutAIR had trouble formatting this lesson. Try again.", html)
        self.assertIn("Formatting hiccup", html)
        self.assertIn("progress_delta: 0", html)
        self.assertNotIn("fallbackText ||", html)

    def test_call_configured_ai_provider_reports_missing_key(self):
        previous = __import__("os").environ.pop("OPENAI_API_KEY", None)
        previous_status = viewer_module._TUTOR_ENV_STATUS
        viewer_module._TUTOR_ENV_STATUS = TutorEnvStatus(
            checked_path=Path("missing/.env"),
            dotenv_installed=False,
            dotenv_loaded=False,
            api_key_found=False,
            message=".env file was not found.",
        )
        try:
            with self.assertRaises(TutorProviderError) as error:
                call_configured_ai_provider([{"role": "user", "content": "Hello"}])
            self.assertIn("OPENAI_API_KEY", str(error.exception))
            self.assertIn(".env", str(error.exception))
        finally:
            viewer_module._TUTOR_ENV_STATUS = previous_status
            if previous is not None:
                __import__("os").environ["OPENAI_API_KEY"] = previous

    def test_load_tutair_env_reads_root_env_file_without_printing_key(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-env-"))
        previous = __import__("os").environ.pop("OPENAI_API_KEY", None)
        try:
            env_path = temp_dir / ".env"
            env_path.write_text("OPENAI_API_KEY=test-secret\nTUTAIR_AI_MODEL=test-model\n", encoding="utf-8")
            status = load_tutair_env(env_path)

            self.assertTrue(status.api_key_found)
            self.assertEqual(status.checked_path, env_path)
            self.assertNotIn("test-secret", status.message)
            self.assertEqual(__import__("os").environ["OPENAI_API_KEY"], "test-secret")
        finally:
            __import__("os").environ.pop("OPENAI_API_KEY", None)
            __import__("os").environ.pop("TUTAIR_AI_MODEL", None)
            if previous is not None:
                __import__("os").environ["OPENAI_API_KEY"] = previous
            shutil.rmtree(temp_dir)

    def test_load_tutair_env_handles_accidental_env_directory(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-env-dir-"))
        previous = __import__("os").environ.pop("OPENAI_API_KEY", None)
        try:
            env_dir = temp_dir / ".env"
            env_dir.mkdir()
            (env_dir / "OPENAI_API_KEY=bad-filename-value.txt").write_text(
                "OPENAI_API_KEY=test-secret-from-file\n",
                encoding="utf-8",
            )
            status = load_tutair_env(env_dir)

            self.assertTrue(status.api_key_found)
            self.assertIn("directory", status.message)
            self.assertEqual(__import__("os").environ["OPENAI_API_KEY"], "test-secret-from-file")
        finally:
            __import__("os").environ.pop("OPENAI_API_KEY", None)
            if previous is not None:
                __import__("os").environ["OPENAI_API_KEY"] = previous
            shutil.rmtree(temp_dir)

    def test_set_env_from_dotenv_line_rejects_invalid_keys(self):
        self.assertFalse(set_env_from_dotenv_line("OPENAI-API-KEY=bad"))

    def test_openai_401_returns_clear_authentication_error_without_key(self):
        previous_key = __import__("os").environ.get("OPENAI_API_KEY")
        previous_model = __import__("os").environ.get("TUTAIR_AI_MODEL")
        previous_status = viewer_module._TUTOR_ENV_STATUS
        previous_urlopen = viewer_module.urlopen
        __import__("os").environ["OPENAI_API_KEY"] = "sk-test-secret-value"
        __import__("os").environ["TUTAIR_AI_MODEL"] = "gpt-4o-mini"
        viewer_module._TUTOR_ENV_STATUS = TutorEnvStatus(
            checked_path=Path("test/.env"),
            dotenv_installed=False,
            dotenv_loaded=True,
            api_key_found=True,
            message="test",
        )

        def fake_urlopen(request, timeout=30):
            body = b'{"error":{"message":"Incorrect API key provided: sk-test-secret-value","type":"invalid_request_error"}}'
            raise HTTPError(request.full_url, 401, "Unauthorized", hdrs=None, fp=BytesIO(body))

        viewer_module.urlopen = fake_urlopen
        try:
            with self.assertRaises(TutorProviderError) as error:
                call_configured_ai_provider([{"role": "user", "content": "Hello"}])
            self.assertIn("authentication failed", str(error.exception))
            self.assertNotIn("sk-test-secret-value", str(error.exception))
        finally:
            viewer_module.urlopen = previous_urlopen
            viewer_module._TUTOR_ENV_STATUS = previous_status
            if previous_key is None:
                __import__("os").environ.pop("OPENAI_API_KEY", None)
            else:
                __import__("os").environ["OPENAI_API_KEY"] = previous_key
            if previous_model is None:
                __import__("os").environ.pop("TUTAIR_AI_MODEL", None)
            else:
                __import__("os").environ["TUTAIR_AI_MODEL"] = previous_model

    def test_sanitize_openai_log_text_redacts_api_keys(self):
        previous_key = __import__("os").environ.get("OPENAI_API_KEY")
        __import__("os").environ["OPENAI_API_KEY"] = "sk-test-secret-value"
        try:
            safe = sanitize_openai_log_text("bad key sk-test-secret-value")
            self.assertNotIn("sk-test-secret-value", safe)
            self.assertIn("<redacted", safe)
        finally:
            if previous_key is None:
                __import__("os").environ.pop("OPENAI_API_KEY", None)
            else:
                __import__("os").environ["OPENAI_API_KEY"] = previous_key


def make_processed_note(root: Path) -> Path:
    capture = TutairCapture(
        source_type="pasted_text",
        subject="Science",
        topic="Cell division",
        source_url="",
        learning_content=(
            "Mitosis makes new body cells. "
            "The parent cell divides to make two identical daughter cells. "
            "This helps organisms grow and repair tissue."
        ),
        captured_on=date(2026, 7, 9),
    )
    source_path = save_source_content(capture, root)
    capture_path = save_capture(with_source_content_fields(capture, source_path), root)
    return process_capture(capture_path)


if __name__ == "__main__":
    unittest.main()
