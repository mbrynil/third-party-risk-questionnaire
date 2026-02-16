from sqlalchemy.orm import Session
from models import (
    Question, ConditionalRule,
    TemplateQuestion, TemplateConditionalRule,
)


def clone_template_to_assessment(db: Session, template_id: int, assessment_id: int) -> dict:
    """Clone questions and rules from an AssessmentTemplate to a live Assessment.

    Reads from TemplateQuestion/TemplateConditionalRule, writes to Question/ConditionalRule.
    Returns a dict mapping template question IDs to new assessment question IDs.
    """
    question_id_map = {}
    source_questions = db.query(TemplateQuestion).filter(
        TemplateQuestion.template_id == template_id
    ).order_by(TemplateQuestion.order).all()

    for sq in source_questions:
        new_q = Question(
            assessment_id=assessment_id,
            question_text=sq.question_text,
            order=sq.order,
            weight=sq.weight,
            expected_operator=sq.expected_operator,
            expected_value=sq.expected_value,
            expected_values=sq.expected_values,
            expected_value_type=sq.expected_value_type,
            answer_mode=sq.answer_mode,
            category=sq.category,
        )
        db.add(new_q)
        db.flush()
        question_id_map[sq.id] = new_q.id

    source_rules = db.query(TemplateConditionalRule).filter(
        TemplateConditionalRule.template_id == template_id
    ).all()

    for rule in source_rules:
        new_trigger = question_id_map.get(rule.trigger_question_id)
        new_target = question_id_map.get(rule.target_question_id)
        if new_trigger and new_target:
            new_rule = ConditionalRule(
                assessment_id=assessment_id,
                trigger_question_id=new_trigger,
                operator=rule.operator,
                trigger_values=rule.trigger_values,
                target_question_id=new_target,
                make_required=rule.make_required,
            )
            db.add(new_rule)

    return question_id_map


def clone_assessment_to_template(db: Session, assessment_id: int, template_id: int) -> dict:
    """Clone questions and rules from a live Assessment to an AssessmentTemplate.

    Reads from Question/ConditionalRule, writes to TemplateQuestion/TemplateConditionalRule.
    Returns a dict mapping assessment question IDs to new template question IDs.
    """
    question_id_map = {}
    source_questions = db.query(Question).filter(
        Question.assessment_id == assessment_id
    ).order_by(Question.order).all()

    for sq in source_questions:
        new_q = TemplateQuestion(
            template_id=template_id,
            question_text=sq.question_text,
            order=sq.order,
            weight=sq.weight,
            expected_operator=sq.expected_operator,
            expected_value=sq.expected_value,
            expected_values=sq.expected_values,
            expected_value_type=sq.expected_value_type,
            answer_mode=sq.answer_mode,
            category=sq.category,
        )
        db.add(new_q)
        db.flush()
        question_id_map[sq.id] = new_q.id

    source_rules = db.query(ConditionalRule).filter(
        ConditionalRule.assessment_id == assessment_id
    ).all()

    for rule in source_rules:
        new_trigger = question_id_map.get(rule.trigger_question_id)
        new_target = question_id_map.get(rule.target_question_id)
        if new_trigger and new_target:
            new_rule = TemplateConditionalRule(
                template_id=template_id,
                trigger_question_id=new_trigger,
                operator=rule.operator,
                trigger_values=rule.trigger_values,
                target_question_id=new_target,
                make_required=rule.make_required,
            )
            db.add(new_rule)

    return question_id_map
