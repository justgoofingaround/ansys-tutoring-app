"""Pydantic request/response models — the API contract — plus the canonical
event taxonomy the overlay and the mining/progress queries agree on."""

from pydantic import BaseModel, Field

# --- Event taxonomy (mining + progress key on these; ingestion accepts any) ---
EVENT_TUTORIAL_STARTED = "tutorial_started"
EVENT_TUTORIAL_COMPLETED = "tutorial_completed"
EVENT_STEP_STARTED = "step_started"
EVENT_STEP_COMPLETED = "step_completed"
EVENT_VERIFY_FAILED = "verify_failed"
EVENT_HINT_SHOWN = "hint_shown"


# --- Auth ---
class RegisterRequest(BaseModel):
    """Roster-based registration: the address must already be on a section's
    roster, which is what assigns the student to that section. The display name
    comes from the roster, so students no longer choose a username."""

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=72)


class ResendRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    # Same floor as registration. bcrypt caps at 72 bytes, so reject above that
    # rather than silently truncating.
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    username: str
    password: str


class MeResponse(BaseModel):
    username: str
    role: str
    section: str | None = None
    opaque_token: str | None = None
    chatbot_consent: bool = False
    # Mirrors Settings.enable_ai so the SPA can hide every AI entry point
    # (Compass, PDF->tutorial import, FAQ drafting) from one source of truth.
    ai_enabled: bool = False


# --- Sections (instructor) ---
class SectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SectionResponse(BaseModel):
    id: int
    name: str
    class_code: str
    is_active: bool
    student_count: int = 0


# --- Events (overlay contract: mirrors sibling event_logger payloads) ---
class ActionEventIn(BaseModel):
    session_token: str | None = None  # overwritten with the authenticated token
    tutorial_id: str
    step_id: str
    action_type: str
    uia_automation_id: str = ""
    timestamp: float
    extra: dict = Field(default_factory=dict)


class ChatQueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    tutorial_id: str | None = None
    step_id: str | None = None
    stream: bool = True


class ChatConsentIn(BaseModel):
    granted: bool


class QuizCheckIn(BaseModel):
    question_id: int
    choice_index: int = Field(ge=0)


class QuizSubmitIn(BaseModel):
    answers: list[int]
    client_score: float | None = None  # client-claimed; server re-grades


class QuizResultIn(BaseModel):
    session_token: str | None = None
    quiz_id: str
    tutorial_id: str
    answers: list[int]
    score: float | None = None  # client-claimed; server re-grades
    timestamp: float
