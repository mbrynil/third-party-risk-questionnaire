"""Compliance Posture service — executive view of framework compliance across the organization."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    FrameworkRequirement, FrameworkAdoption, ControlImplementation, ControlTest, Control,
    CustomFramework,
    SEEDED_FRAMEWORKS, AVAILABLE_FRAMEWORKS, FRAMEWORK_DISPLAY,
    ADOPTION_STATUS_MAPPED, ADOPTION_STATUS_NOT_APPLICABLE,
    IMPL_STATUS_IMPLEMENTED,
    TEST_STATUS_COMPLETED,
    TEST_RESULT_PASS,
)


def get_compliance_posture(db: Session) -> dict:
    """Compute compliance posture for every framework with requirements."""

    # Build full list of framework keys + display names
    all_fw = list(AVAILABLE_FRAMEWORKS)
    customs = db.query(CustomFramework).filter(CustomFramework.is_active == True).all()
    for c in customs:
        all_fw.append((c.framework_key, c.display_name))

    display_map = {k: v for k, v in all_fw}
    twelve_months_ago = datetime.utcnow() - timedelta(days=365)

    postures = []

    for fw_key, display_name in all_fw:
        # Total active requirements
        total_requirements = db.query(FrameworkRequirement).filter(
            FrameworkRequirement.framework == fw_key,
            FrameworkRequirement.is_active == True,
        ).count()

        if total_requirements == 0:
            continue

        # Adoptions for this framework
        adoptions = db.query(FrameworkAdoption).filter(
            FrameworkAdoption.framework == fw_key,
        ).all()

        adopted_count = sum(1 for a in adoptions if a.status == ADOPTION_STATUS_MAPPED)
        na_count = sum(1 for a in adoptions if a.status == ADOPTION_STATUS_NOT_APPLICABLE)
        gap_count = total_requirements - adopted_count - na_count

        # Controls mapped (adopted with a control_id set)
        mapped_control_ids = list(set(
            a.control_id for a in adoptions
            if a.status == ADOPTION_STATUS_MAPPED and a.control_id
        ))
        controls_mapped = len(mapped_control_ids)

        # Of those mapped controls, how many have a COMPLETED test in last 12 months?
        controls_tested = 0
        controls_passing = 0

        if mapped_control_ids:
            # Get org-level implementations for these controls
            impl_rows = db.query(
                ControlImplementation.id,
                ControlImplementation.control_id,
            ).filter(
                ControlImplementation.control_id.in_(mapped_control_ids),
                ControlImplementation.vendor_id == None,
            ).all()

            impl_map = {row.id: row.control_id for row in impl_rows}
            impl_ids = list(impl_map.keys())

            if impl_ids:
                # Find latest test per implementation in last 12 months
                from sqlalchemy import case
                latest_tests = db.query(
                    ControlTest.implementation_id,
                    func.max(ControlTest.test_date).label("latest_date"),
                ).filter(
                    ControlTest.implementation_id.in_(impl_ids),
                    ControlTest.status == TEST_STATUS_COMPLETED,
                    ControlTest.test_date != None,
                    ControlTest.test_date >= twelve_months_ago,
                ).group_by(ControlTest.implementation_id).all()

                tested_impl_ids = [lt.implementation_id for lt in latest_tests]
                tested_control_ids = set(impl_map[iid] for iid in tested_impl_ids if iid in impl_map)
                controls_tested = len(tested_control_ids)

                # Of tested, find passing (most recent test result = PASS)
                if tested_impl_ids:
                    for impl_id in tested_impl_ids:
                        most_recent = db.query(ControlTest).filter(
                            ControlTest.implementation_id == impl_id,
                            ControlTest.status == TEST_STATUS_COMPLETED,
                            ControlTest.test_date != None,
                        ).order_by(ControlTest.test_date.desc()).first()
                        if most_recent and most_recent.result == TEST_RESULT_PASS:
                            controls_passing += 1

        # Compute percentages
        applicable = total_requirements - na_count
        compliance_pct = round((adopted_count / applicable) * 100, 1) if applicable > 0 else 0.0
        test_coverage_pct = round((controls_tested / controls_mapped) * 100, 1) if controls_mapped > 0 else 0.0
        test_pass_pct = round((controls_passing / controls_tested) * 100, 1) if controls_tested > 0 else 0.0

        # Health rating
        if compliance_pct >= 80:
            health = "Good"
            health_color = "#198754"
        elif compliance_pct >= 50:
            health = "Fair"
            health_color = "#ffc107"
        else:
            health = "Needs Attention"
            health_color = "#dc3545"

        postures.append({
            "framework_key": fw_key,
            "display_name": display_name,
            "total_requirements": total_requirements,
            "adopted_count": adopted_count,
            "na_count": na_count,
            "gap_count": gap_count,
            "controls_mapped": controls_mapped,
            "controls_tested": controls_tested,
            "controls_passing": controls_passing,
            "compliance_pct": compliance_pct,
            "test_coverage_pct": test_coverage_pct,
            "test_pass_pct": test_pass_pct,
            "health": health,
            "health_color": health_color,
        })

    # Sort by compliance % descending
    postures.sort(key=lambda p: p["compliance_pct"], reverse=True)

    # Compute overall metrics
    total_applicable = sum(p["total_requirements"] - p["na_count"] for p in postures)
    total_adopted = sum(p["adopted_count"] for p in postures)
    overall_compliance_pct = round((total_adopted / total_applicable) * 100, 1) if total_applicable > 0 else 0.0
    total_gaps = sum(p["gap_count"] for p in postures)
    frameworks_above_80 = sum(1 for p in postures if p["compliance_pct"] >= 80)

    return {
        "postures": postures,
        "overall_pct": overall_compliance_pct,
        "total_gaps": total_gaps,
        "frameworks_tracked": len(postures),
        "frameworks_above_80": frameworks_above_80,
    }
