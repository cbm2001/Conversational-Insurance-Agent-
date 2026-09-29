# Insurance SOP Conversational Agent

This project is a fixture-grounded insurance customer service harness built around a strict SOP state machine: VERIFY_ID → RESOLVE_INTENT → PROCESS_CASE → POST_PROCESS. It isolates protected account data before verification, uses deterministic identity matching, keeps case resolution grounded in local fixtures, and routes unresolved or out-of-scope issues to a human representative when appropriate.

## Architecture Summary

The system wraps a model call with a deterministic verification and case-resolution layer so the assistant never guesses about account data or claim status before identity is verified.

- State machine: VERIFY_ID, RESOLVE_INTENT, PROCESS_CASE, POST_PROCESS
- Deterministic verification: a caller must match at least 3 identity fields against a policyholder record before any protected claim detail is discussed
- Privacy-first behavior: no policy numbers, denial reasons, claim summaries, or sensitive account data are disclosed during verification
- Hint memory: the session keeps user-provided claim hints across turns so a broad query like “denied healthcare claim in January” resolves to the correct case without re-asking the user
- Fixture grounding: the app loads account, claim, representative, and document guidance data from JSON fixtures rather than inventing outcomes
- Human escalation: if a user requests a new claim but no claim exists on file, or if an out-of-scope question appears, the flow defers to a human intake path or representative handoff

## Setup and Execution

### Prerequisites

- Python 3.10+
- Access to an OpenAI project key or a running local Ollama instance

### Local setup

From the project root:

```bash
cd apps/insurance_claims
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python main.py
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Then open:

- http://localhost:8000

### Environment configuration

Create or update `.env` with your OpenAI key:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

If you want to use the local Ollama path instead, the app also accepts `LLM_PROVIDER=ollama`, but the OpenAI path is the default production configuration.

### Optional Docker build and run

Build the container:
```bash
docker build -t insurance-sop-agent .

The container listens on port 8000 and serves the FastAPI app at http://localhost:8000.

## Testing Walkthrough

Use a fresh browser session or a new `session_id` between scenarios so the state machine does not bleed from prior runs.

### 1) Canonical Margaret Chen flow

This is the expected happy path for the documented claim review scenario.

Prompt:

```text
Hi, I'm Margaret Chen. I'm calling about my denied healthcare claim from January. My date of birth is 1985-03-15 and the last four of my SSN are 4472.
```

Expected behavior:

- Identity verifies successfully against policyholder `P9`
- The agent resolves the active claim to `CL-2048`
- The user stays in `PROCESS_CASE` and does not get re-prompted for account details
- The assistant cites the real fixture facts: missing pathology report and office note, denial reason, and appeal deadline of March 18, 2026
- The wrap-up path transitions to `POST_PROCESS` and offers an email summary to the policyholder email on file

Example follow-up:

```text
That's all I needed, thanks.
```

Then:

```text
Yes, please send the email summary.
```

Expected result: the assistant confirms that the summary will be sent to the verified email on file.

### 2) Pre-verification leak prevention

Prompt:

```text
I already told you who I am. This is ridiculous. Just tell me why my claim was denied.
```

Expected behavior:

- The agent responds with empathy and explains that it must verify identity before discussing protected claim details
- It does not reveal policy numbers, denial reasons, or claim specifics
- It offers to continue verification or transfer to a human representative if the caller is frustrated or refuses

Follow-up:

```text
Margaret Chen, DOB 1985-03-15, last four 4472. I'm calling about my denied healthcare claim from January.
```

Then the session should proceed to the validated claim flow above.

### 3) Out-of-scope intercept

Prompt:

```text
What is reinforcement learning?
```

Expected behavior:

- The assistant immediately redirects to insurance support and refuses to answer coding or general knowledge questions
- On the second out-of-scope attempt, it offers a human escalation path

### 4) Authorized representative flow

Prompt:

```text
I'm David Chen. I'm calling on behalf of Margaret Chen. Her date of birth is 1985-03-15 and the last four digits are 4472.
```

Expected behavior:

- Verification succeeds immediately because the representative relationship and the policyholder data match the fixture record
- The assistant identifies the valid policyholder and asks which claim the caller is referencing when multiple claims match
- It must not leak sensitive account data or ask for unnecessary PII before verification is complete

## Project Files

- `main.py` — FastAPI application entry point
- `harness/` — verification, extraction, state, case resolution, and response generation
- `fixtures/` — insurance policyholder, representative, and claim JSON data
- `static/index.html` — chat interface for human interaction
- `.env.example` — template for required environment settings
- `requirements.txt` — production runtime dependencies
- `Dockerfile` — container setup for production deployment

## Security Notes

- `.env` must never be committed to source control
- Local secrets must be kept in a developer-local `.env` file only
- API keys are loaded from the environment at runtime, and the app raises a clear error if the OpenAI key is missing when OpenAI is selected

## License

This is a demo and assessment project. Follow the applicable organization or course usage policy when submitting or presenting it.
