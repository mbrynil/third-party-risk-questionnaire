"""Seed script: creates a second analyst user and assigns vendors/assessments
to both admin and analyst so the My Workspace dashboards have real data.

Run once:  python seed_workspace.py
"""
import random
from datetime import datetime, timedelta

import bcrypt
from models import (
    SessionLocal, User, Vendor, Assessment, RemediationItem, VendorActivity,
    VENDOR_STATUS_ACTIVE,
    ASSESSMENT_STATUS_DRAFT, ASSESSMENT_STATUS_SENT,
    ASSESSMENT_STATUS_IN_PROGRESS, ASSESSMENT_STATUS_SUBMITTED,
    REMEDIATION_STATUS_OPEN, REMEDIATION_STATUS_IN_PROGRESS,
    REMEDIATION_SOURCE_MANUAL,
    ACTIVITY_VENDOR_CREATED, ACTIVITY_ASSESSMENT_CREATED,
    ACTIVITY_ASSESSMENT_SENT, ACTIVITY_VENDOR_SUBMITTED,
    ACTIVITY_ANALYST_ASSIGNED, ACTIVITY_DECISION_FINALIZED,
)

random.seed(99)


def main():
    db = SessionLocal()
    try:
        # ==================== 1. ENSURE ANALYST USER ====================
        analyst = db.query(User).filter(User.email == "analyst@example.com").first()
        if not analyst:
            hashed = bcrypt.hashpw("changeme".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            analyst = User(
                email="analyst@example.com",
                display_name="Jordan Rivera",
                password_hash=hashed,
                role="analyst",
                is_active=True,
            )
            db.add(analyst)
            db.flush()
            print(f"Created analyst user: analyst@example.com / changeme (id={analyst.id})")
        else:
            print(f"Analyst user already exists (id={analyst.id})")

        admin = db.query(User).filter(User.role == "admin").first()
        if not admin:
            print("ERROR: No admin user found. Start the app first.")
            return
        print(f"Admin user: {admin.email} (id={admin.id})")

        # ==================== 2. ASSIGN VENDORS ====================
        active_vendors = db.query(Vendor).filter(
            Vendor.status == VENDOR_STATUS_ACTIVE
        ).order_by(Vendor.id).all()

        if not active_vendors:
            print("ERROR: No active vendors. Run seed_demo.py first.")
            return

        print(f"Found {len(active_vendors)} active vendors")

        # Split vendors: ~60% to admin, ~40% to analyst, leave a couple unassigned
        for i, v in enumerate(active_vendors):
            if v.assigned_analyst_id:
                continue  # already assigned
            if i < len(active_vendors) * 0.55:
                v.assigned_analyst_id = admin.id
            elif i < len(active_vendors) * 0.9:
                v.assigned_analyst_id = analyst.id
            # else: leave unassigned
        db.flush()

        admin_vendors = [v for v in active_vendors if v.assigned_analyst_id == admin.id]
        analyst_vendors = [v for v in active_vendors if v.assigned_analyst_id == analyst.id]
        unassigned = [v for v in active_vendors if not v.assigned_analyst_id]
        print(f"Assigned: {len(admin_vendors)} to admin, {len(analyst_vendors)} to analyst, {len(unassigned)} unassigned")

        # ==================== 3. ASSIGN ASSESSMENTS ====================
        all_assessments = db.query(Assessment).all()
        assigned_count = 0
        for a in all_assessments:
            if a.assigned_analyst_id:
                continue
            # Most inherit from vendor (leave NULL), but directly assign a few
            if random.random() < 0.3 and a.vendor:
                # Direct assessment assignment (sometimes to the other analyst for variety)
                if a.vendor.assigned_analyst_id == admin.id and random.random() < 0.3:
                    a.assigned_analyst_id = analyst.id
                elif a.vendor.assigned_analyst_id == analyst.id and random.random() < 0.3:
                    a.assigned_analyst_id = admin.id
                else:
                    a.assigned_analyst_id = a.vendor.assigned_analyst_id
                assigned_count += 1
        db.flush()
        print(f"Directly assigned {assigned_count} assessments at assessment level")

        # ==================== 4. ADD REMEDIATIONS FOR WORKSPACE ====================
        now = datetime.utcnow()
        remediation_titles = [
            "Implement MFA for privileged accounts",
            "Update incident response plan",
            "Configure SIEM log forwarding",
            "Complete SOC 2 Type II audit",
            "Establish encryption key rotation policy",
            "Conduct annual penetration test",
            "Implement network segmentation",
            "Deploy endpoint detection and response",
            "Create vendor risk management program",
            "Update business continuity plan",
            "Remediate critical vulnerability CVE-2025-1234",
            "Enable audit logging for database access",
        ]

        # Check if we already seeded remediations
        existing_manual = db.query(RemediationItem).filter(
            RemediationItem.source == REMEDIATION_SOURCE_MANUAL,
            RemediationItem.title.in_(remediation_titles),
        ).count()

        if existing_manual == 0:
            created_rems = 0
            for v in admin_vendors + analyst_vendors:
                # 2-4 remediations per vendor
                count = random.randint(1, 4)
                titles = random.sample(remediation_titles, min(count, len(remediation_titles)))
                for title in titles:
                    days_offset = random.randint(-30, 90)  # some overdue, some future
                    due = now + timedelta(days=days_offset)
                    status = random.choice([
                        REMEDIATION_STATUS_OPEN, REMEDIATION_STATUS_OPEN,
                        REMEDIATION_STATUS_IN_PROGRESS,
                    ])
                    # Assign to the vendor's analyst or to admin
                    assigned_user = v.assigned_analyst_id
                    if random.random() < 0.3:
                        assigned_user = admin.id if v.assigned_analyst_id == analyst.id else analyst.id

                    rem = RemediationItem(
                        vendor_id=v.id,
                        title=title,
                        description=f"Remediation item for {v.name}: {title}",
                        source=REMEDIATION_SOURCE_MANUAL,
                        severity=random.choice(["CRITICAL", "HIGH", "MEDIUM", "LOW"]),
                        status=status,
                        assigned_to_user_id=assigned_user,
                        due_date=due,
                        created_at=now - timedelta(days=random.randint(5, 60)),
                    )
                    db.add(rem)
                    created_rems += 1
            db.flush()
            print(f"Created {created_rems} remediation items")
        else:
            print(f"Remediations already seeded ({existing_manual} found)")

        # ==================== 5. ADD ACTIVITY ENTRIES ====================
        existing_activities = db.query(VendorActivity).count()
        if existing_activities < 20:
            activity_types = [
                (ACTIVITY_ANALYST_ASSIGNED, "Analyst assigned to vendor"),
                (ACTIVITY_ASSESSMENT_CREATED, "New assessment created"),
                (ACTIVITY_ASSESSMENT_SENT, "Assessment sent to vendor contact"),
                (ACTIVITY_VENDOR_SUBMITTED, "Vendor submitted assessment response"),
                (ACTIVITY_DECISION_FINALIZED, "Assessment decision finalized"),
            ]
            created_acts = 0
            for v in admin_vendors + analyst_vendors:
                for _ in range(random.randint(2, 5)):
                    act_type, desc = random.choice(activity_types)
                    user_id = v.assigned_analyst_id or admin.id
                    act = VendorActivity(
                        vendor_id=v.id,
                        activity_type=act_type,
                        description=f"{desc} — {v.name}",
                        user_id=user_id,
                        created_at=now - timedelta(
                            days=random.randint(0, 30),
                            hours=random.randint(0, 23),
                            minutes=random.randint(0, 59),
                        ),
                    )
                    db.add(act)
                    created_acts += 1
            db.flush()
            print(f"Created {created_acts} activity entries")
        else:
            print(f"Activities already populated ({existing_activities} found)")

        db.commit()
        print("\nDone! Login credentials:")
        print(f"  Admin:   admin@example.com / changeme")
        print(f"  Analyst: analyst@example.com / changeme")

    finally:
        db.close()


if __name__ == "__main__":
    main()
