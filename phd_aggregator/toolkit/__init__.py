"""toolkit — writing/survey helpers extracted from the phd_aggregator monolith
(migration Step 10): customized contact emails, professor lists, scholarships.
"""

from toolkit.emails import (  # noqa: F401
    APPLICANT_PROFILE,
    _EMAIL_FIT_FALLBACK,
    _EMAIL_FIT_RULES,
    _ensure_applicant_profile,
    _slugify,
    build_email,
    write_emails,
)
from toolkit.professors import (  # noqa: F401
    PROFESSOR_ARXIV_QUERIES,
    PROFESSOR_SEED,
    _arxiv_author_survey,
    find_professors,
)
from toolkit.scholarships import (  # noqa: F401
    SCHOLARSHIPS,
    _SCHOLARSHIP_PRACTICAL_NOTES,
    write_scholarships,
)
