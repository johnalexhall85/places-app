from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db import Base
from app.funding_models.constants import FUNDING_MODELS_SCHEMA


class FundingProfileModel(Base):
    __tablename__ = "funding_profile_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    display_name = Column(Text, nullable=False)
    internal_model_id = Column(Text, nullable=False)
    slug = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    chip_methodology_version = Column(Text, nullable=False)
    funding_mode_key = Column(Text, nullable=False)
    status = Column(Text, nullable=False, server_default=text("'draft'"))
    is_system = Column(Boolean, nullable=False, server_default=text("false"))
    is_user_editable = Column(Boolean, nullable=False, server_default=text("true"))
    is_visible_in_funding_mode = Column(Boolean, nullable=False, server_default=text("false"))
    toolbar_page_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    created_by = Column(Text, nullable=False, server_default=text("'system'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    current_version_id = Column(
        Integer,
        ForeignKey(f"{FUNDING_MODELS_SCHEMA}.funding_profile_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    versions = relationship(
        "FundingProfileVersion",
        back_populates="profile_model",
        foreign_keys="FundingProfileVersion.profile_model_id",
        order_by="FundingProfileVersion.version_number.desc()",
    )
    current_version = relationship(
        "FundingProfileVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )
    registry_entries = relationship("FundingModeRegistryEntry", back_populates="profile_model")

    __table_args__ = (
        UniqueConstraint("internal_model_id", name="uq_funding_profile_models_internal_model_id"),
        UniqueConstraint("slug", name="uq_funding_profile_models_slug"),
        Index("funding_profile_models_status_idx", "status"),
        Index("funding_profile_models_mode_key_idx", "funding_mode_key"),
        {"schema": FUNDING_MODELS_SCHEMA},
    )


class FundingProfileVersion(Base):
    __tablename__ = "funding_profile_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_model_id = Column(
        Integer,
        ForeignKey(f"{FUNDING_MODELS_SCHEMA}.funding_profile_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = Column(Integer, nullable=False)
    version_label = Column(Text, nullable=True)
    definition_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    generated_sql = Column(Text, nullable=True)
    advanced_sql_override = Column(Text, nullable=True)
    plain_language_summary = Column(Text, nullable=False, server_default=text("''"))
    chip_state_profile_source_version = Column(Text, nullable=True)
    chip_normalization_source_version = Column(Text, nullable=True)
    build_script_name = Column(Text, nullable=True)
    build_status = Column(Text, nullable=True)
    validation_status = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Text, nullable=False, server_default=text("'system'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    profile_model = relationship(
        "FundingProfileModel",
        back_populates="versions",
        foreign_keys=[profile_model_id],
    )
    build_runs = relationship("FundingProfileBuildRun", back_populates="profile_version")
    registry_entries = relationship("FundingModeRegistryEntry", back_populates="profile_version")

    __table_args__ = (
        UniqueConstraint(
            "profile_model_id",
            "version_number",
            name="uq_funding_profile_versions_model_version",
        ),
        Index("funding_profile_versions_build_status_idx", "build_status"),
        Index("funding_profile_versions_validation_status_idx", "validation_status"),
        {"schema": FUNDING_MODELS_SCHEMA},
    )


class FundingProfileBuildRun(Base):
    __tablename__ = "funding_profile_build_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_version_id = Column(
        Integer,
        ForeignKey(f"{FUNDING_MODELS_SCHEMA}.funding_profile_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_type = Column(Text, nullable=False)
    script_name = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False)
    log_excerpt = Column(Text, nullable=True)
    output_table_name = Column(Text, nullable=True)
    output_view_name = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    profile_version = relationship("FundingProfileVersion", back_populates="build_runs")

    __table_args__ = (
        Index("funding_profile_build_runs_version_idx", "profile_version_id"),
        Index("funding_profile_build_runs_status_idx", "status"),
        {"schema": FUNDING_MODELS_SCHEMA},
    )


class FundingModeRegistryEntry(Base):
    __tablename__ = "funding_mode_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    funding_mode_key = Column(Text, nullable=False)
    label = Column(Text, nullable=False)
    profile_model_id = Column(
        Integer,
        ForeignKey(f"{FUNDING_MODELS_SCHEMA}.funding_profile_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_version_id = Column(
        Integer,
        ForeignKey(f"{FUNDING_MODELS_SCHEMA}.funding_profile_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    map_default = Column(Boolean, nullable=False, server_default=text("false"))
    sort_order = Column(Integer, nullable=False, server_default=text("100"))
    is_active = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    profile_model = relationship("FundingProfileModel", back_populates="registry_entries")
    profile_version = relationship("FundingProfileVersion", back_populates="registry_entries")

    __table_args__ = (
        UniqueConstraint("funding_mode_key", name="uq_funding_mode_registry_key"),
        Index("funding_mode_registry_active_idx", "is_active"),
        Index("funding_mode_registry_sort_idx", "sort_order"),
        {"schema": FUNDING_MODELS_SCHEMA},
    )
