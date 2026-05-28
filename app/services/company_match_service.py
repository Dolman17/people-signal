import re

from sqlalchemy import func

from app.extensions import db
from app.models import Company, CompanyAlias


def normalise_company_name(name):
    """
    Normalises company names for safer matching.
    This is deliberately conservative.
    """

    if not name:
        return ""

    value = name.lower().strip()

    value = re.sub(r"\blimited\b", "ltd", value)
    value = re.sub(r"\bltd\.\b", "ltd", value)
    value = re.sub(r"\bcare home\b", "", value)
    value = re.sub(r"\bcare centre\b", "", value)
    value = re.sub(r"\bnursing home\b", "", value)
    value = re.sub(r"\bresidential home\b", "", value)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" -.,()[]{}")

    return value


def find_company_by_name_or_alias(company_name):
    """
    Looks for an existing Company by:
    1. Exact case-insensitive company name
    2. Exact case-insensitive alias
    3. Conservative normalised company/alias match
    """

    if not company_name:
        return None

    clean_name = company_name.strip()
    normalised_name = normalise_company_name(clean_name)

    exact_company = (
        Company.query
        .filter(func.lower(Company.name) == clean_name.lower())
        .first()
    )

    if exact_company:
        return exact_company

    exact_alias = (
        CompanyAlias.query
        .filter(func.lower(CompanyAlias.alias_name) == clean_name.lower())
        .first()
    )

    if exact_alias:
        return exact_alias.company

    companies = Company.query.all()

    for company in companies:
        if normalise_company_name(company.name) == normalised_name:
            return company

    aliases = CompanyAlias.query.all()

    for alias in aliases:
        if normalise_company_name(alias.alias_name) == normalised_name:
            return alias.company

    return None


def add_company_alias(company, alias_name, source="system"):
    """
    Adds an alias to a company if it does not already exist.
    """

    if not company or not alias_name:
        return None

    alias_name = alias_name.strip()

    if not alias_name:
        return None

    if alias_name.lower() == company.name.lower():
        return None

    existing_alias = (
        CompanyAlias.query
        .filter(
            CompanyAlias.company_id == company.id,
            func.lower(CompanyAlias.alias_name) == alias_name.lower()
        )
        .first()
    )

    if existing_alias:
        return existing_alias

    alias = CompanyAlias(
        company_id=company.id,
        alias_name=alias_name[:255],
        source=source,
    )

    db.session.add(alias)

    return alias