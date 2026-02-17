from models import compute_expectation_status


def compute_response_evaluations(questions: list, response) -> dict:
    """Build {question_id: eval_status} dict for a single response."""
    answers_dict = {a.question_id: a for a in response.answers}
    eval_dict = {}
    for q in questions:
        answer = answers_dict.get(q.id)
        answer_choice = answer.answer_choice if answer else None
        eval_dict[q.id] = compute_expectation_status(
            q.expected_value, answer_choice, q.expected_values, q.answer_mode,
            answer_options=q.answer_options
        )
    return eval_dict


def compute_expectation_stats(questions: list, response) -> dict:
    """Compute meets/partial/does_not_meet/no_expectation counts for a response."""
    meets = 0
    partial = 0
    does_not_meet = 0
    no_expectation = 0

    if response:
        answers = {a.question_id: a for a in response.answers}
        for q in questions:
            answer = answers.get(q.id)
            if answer:
                status = compute_expectation_status(
                    q.expected_value,
                    answer.answer_choice,
                    q.expected_values,
                    q.answer_mode,
                    answer_options=q.answer_options,
                )
                if status == "MEETS_EXPECTATION":
                    meets += 1
                elif status == "PARTIALLY_MEETS_EXPECTATION":
                    partial += 1
                elif status == "DOES_NOT_MEET_EXPECTATION":
                    does_not_meet += 1
                else:
                    no_expectation += 1
            else:
                no_expectation += 1
    else:
        no_expectation = len(questions)

    return {
        "meets_count": meets,
        "partial_count": partial,
        "does_not_meet_count": does_not_meet,
        "no_expectation_count": no_expectation,
    }
