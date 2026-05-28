from app import create_app
from app.extensions import db
from app.models import Company, LeadSignal, AIInsight, SourceRunLog


app = create_app()


def reset_operational_data():
    with app.app_context():
        print("PeopleSignal data reset")
        print("-" * 30)
        print("This will delete:")
        print("- AI insights")
        print("- Lead signals")
        print("- Companies")
        print("- Source run logs")
        print()
        print("This will keep:")
        print("- Users")
        print("- Organisations")
        print("- Login accounts")
        print()

        confirm = input("Type RESET to continue: ").strip()

        if confirm != "RESET":
            print("Reset cancelled.")
            return

        ai_insights_deleted = AIInsight.query.delete()
        lead_signals_deleted = LeadSignal.query.delete()
        companies_deleted = Company.query.delete()
        source_runs_deleted = SourceRunLog.query.delete()

        db.session.commit()

        print()
        print("Reset complete.")
        print(f"AI insights deleted: {ai_insights_deleted}")
        print(f"Lead signals deleted: {lead_signals_deleted}")
        print(f"Companies deleted: {companies_deleted}")
        print(f"Source run logs deleted: {source_runs_deleted}")


if __name__ == "__main__":
    reset_operational_data()