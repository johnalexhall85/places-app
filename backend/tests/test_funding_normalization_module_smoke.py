from __future__ import annotations

from app.cdc_profiles import models as cdc_profile_models
from app.db_schemas import CDC_PROFILES_SCHEMA, RECON_SCHEMA
from app.recon import models as recon_models


def test_cdc_profile_models_use_cdc_profiles_schema() -> None:
    assert CDC_PROFILES_SCHEMA == "cdc_profiles"
    assert cdc_profile_models.CdcProfileRawRow.__table__.schema == CDC_PROFILES_SCHEMA
    assert cdc_profile_models.CdcProfileStateYearTotal.__table__.schema == CDC_PROFILES_SCHEMA
    assert cdc_profile_models.CdcProfileMethodologyDocument.__table__.schema == CDC_PROFILES_SCHEMA


def test_recon_models_use_recon_schema() -> None:
    assert RECON_SCHEMA == "recon"
    assert recon_models.CdcProfileCalibration.__table__.schema == RECON_SCHEMA
    assert recon_models.NormalizationRuleByYear.__table__.schema == RECON_SCHEMA
    assert recon_models.NormalizedStateFunding.__table__.schema == RECON_SCHEMA
    assert recon_models.NormalizationMethodologyLog.__table__.schema == RECON_SCHEMA
    assert recon_models.DefcClassificationRule.__table__.schema == RECON_SCHEMA
    assert recon_models.AppropriationTypeRule.__table__.schema == RECON_SCHEMA
    assert recon_models.FederalAccountInclusionRule.__table__.schema == RECON_SCHEMA
    assert recon_models.CdcProfileScopeRule.__table__.schema == RECON_SCHEMA
    assert recon_models.FederalAccountLookup.__table__.schema == RECON_SCHEMA
    assert recon_models.FederalAccountObservation.__table__.schema == RECON_SCHEMA
    assert recon_models.FederalAccountClassificationRule.__table__.schema == RECON_SCHEMA
    assert recon_models.UsaspendingFundingStream.__table__.schema == RECON_SCHEMA
    assert recon_models.TaggsFundingStream.__table__.schema == RECON_SCHEMA
