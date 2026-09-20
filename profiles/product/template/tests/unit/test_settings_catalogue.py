"""The settings this product declares, and the rules the catalogue must keep.

The definitions themselves are validated by `koras_settings` at import -- a bad
default or an enum with no options never reaches a test, because the process
does not start. What is asserted here is what the framework cannot know: that
the *product's* catalogue says what the design says it says.

The most valuable one is the scope-and-visibility pair. `SettingDefinition`
refuses a setting offered to a person that no person may write; it cannot refuse
the opposite mistake -- a setting a person may write and is never shown -- and
that one is invisible until somebody asks why their preference page is short.
"""

from __future__ import annotations

from pathlib import Path

from koras_api.settings_catalogue import catalogue
from koras_api.settings_catalogue.standard import LANGUAGE_OPTIONS, LOCALES
from koras_settings import Category, DataType, Scope

API = Path(__file__).resolve().parents[2] / "services" / "api" / "koras_api"


def test_the_catalogue_is_assembled_and_not_empty() -> None:
    """It is built at import, so this failing means the process would not start."""
    assert len(catalogue) >= 32


def test_grid_page_size_is_fifty_and_paging_is_on() -> None:
    """The one number the brief states outright."""
    page_size = catalogue.require("grid.pageSize")
    assert page_size.default == 50
    assert page_size.minimum == 10
    assert page_size.maximum == 500
    assert catalogue.require("grid.paginationEnabled").default is True
    assert catalogue.require("grid.pageSizeOptions").default == ("10", "25", "50", "100", "250")


def test_every_grid_setting_the_table_reads_is_declared() -> None:
    """The shared table resolves these ten by name.

    A rename here without a rename there is a component silently falling back
    to a default, which looks like the setting simply not working.
    """
    expected = {
        "grid.pageSize",
        "grid.pageSizeOptions",
        "grid.paginationEnabled",
        "grid.stickyHeader",
        "grid.allowColumnResize",
        "grid.allowColumnReorder",
        "grid.rememberFilters",
        "grid.rememberSort",
        "grid.rememberColumns",
        "grid.rowDensity",
    }
    declared = {s.key for s in catalogue if s.category is Category.GRID}
    assert declared == expected


def test_a_person_is_offered_exactly_what_a_person_may_write() -> None:
    """Both directions, allowing for a setting nothing honours yet.

    The definition refuses a setting offered to a person no person may write;
    nothing but this refuses the opposite, which produces a preferences page
    missing something somebody was told they could change.

    The exception is `surfaced=False`: a setting the product declares and no
    code honours is shown on neither customer page, whatever its scope. Those
    are named rather than derived, so removing `surfaced=False` from one and
    forgetting its two translations is a failure here as well as in the
    generator's catalogue test.
    """
    unhonoured = {
        # Two of the original five. The shared table learned column resizing,
        # reordering and remembering an arrangement on 2026-09-19, so three of
        # them left this set; these two stay, with a sharper reason than "the
        # table does not honour them". The table has no filter and no sort, so
        # they describe persistence of state it does not own -- a surface above
        # it does. They leave when it grows sorting and filtering, or they
        # leave the catalogue.
        "grid.rememberFilters",
        "grid.rememberSort",
        # Added 2026-09-19 with the notification feed. All three
        # `notifications.*` settings were offered and honoured by nothing from
        # the day the framework shipped -- a customer could switch off
        # notification emails and still receive them. `inAppEnabled` was
        # honoured first; `emailEnabled` is honoured since CAT-01 Phase 2 moved
        # the one mail a product sends onto the dispatch point, and left this
        # set on 2026-09-19. The digest waits for an outbox to accumulate into,
        # which is Phase 3.
        "notifications.digestFrequency",
        # Added 2026-09-19 with data import, which enforced the other two
        # file settings at the presign route and found this one has no
        # moment to apply: one ticket, one file.
        "files.maxFilesPerUpload",
    }
    for setting in catalogue:
        if setting.key in unhonoured:
            assert not setting.user_visible, f"{setting.key} is offered and nothing honours it"
            assert not setting.org_admin_visible, f"{setting.key} is shown and nothing honours it"
        elif setting.scope is Scope.GLOBAL_ORG_USER:
            assert setting.user_visible, f"{setting.key} may be overridden and is never offered"
        else:
            assert not setting.user_visible, f"{setting.key} is offered and cannot be overridden"


def test_the_limits_belong_to_the_organisation_and_not_to_a_person() -> None:
    """An upload limit each person sets for themselves is not a limit."""
    for key in ("files.maxUploadSizeMb", "files.allowedExtensions", "files.maxFilesPerUpload"):
        assert catalogue.require(key).scope is Scope.GLOBAL_ORG


def test_every_definition_derives_its_two_i18n_keys_from_its_own(  # noqa: D103
) -> None:
    for setting in catalogue:
        assert setting.label_key == f"settings.def.{setting.key}.label"
        assert setting.description_key == f"settings.def.{setting.key}.description"


def test_no_setting_is_named_like_a_credential() -> None:
    """The database refuses one; this refuses it a deploy earlier.

    `00029`'s check constraint would reject the row at write time, which is a
    500 on somebody's settings page rather than a red build.
    """
    forbidden = ("secret", "token", "password", "credential", "apikey", "accesskey", "privatekey")
    for setting in catalogue:
        flattened = setting.key.replace("_", "").lower()
        for word in forbidden:
            assert word not in flattened, f"{setting.key} is named like a credential"


def test_the_language_options_are_the_ones_the_api_accepts() -> None:
    """Three copies of one list, and this is where two of them meet.

    `packages/i18n` declares what the frontend can speak, `routers/tenant.py`
    holds the same list because the two runtimes cannot import each other, and
    the catalogue constrains the stored value. A language offered here and
    refused there is a setting whose own control produces a 422.
    """
    router = (API / "routers" / "tenant.py").read_text(encoding="utf-8")
    declared = router.split("SUPPORTED_LOCALES: tuple[str, ...] = (", 1)[1].split(")", 1)[0]
    in_router = tuple(
        part.strip().strip('"').strip("'") for part in declared.split(",") if part.strip()
    )

    assert LOCALES == in_router

    # The setting offers one more than the API stores: `auto`, which is how a
    # seeded row says "nobody chose". Without it the snapshot would put a real
    # language in every tenant at provisioning, `Accept-Language` would never be
    # consulted again, and a German browser would be answered in English.
    language = catalogue.require("general.language")
    assert language.options == ("auto", *LOCALES) == LANGUAGE_OPTIONS
    assert language.default == "auto"


def test_the_extension_point_ships_empty() -> None:
    """A product adds its own settings; the starter ships none of them.

    The same assertion `reporting/reports.py` gets, and for the same reason: an
    example left in the list is a setting every product carries by accident.
    """
    from koras_api.settings_catalogue import product

    assert product.SETTINGS == []


def test_an_enum_never_offers_a_value_outside_its_options() -> None:
    """Belt and braces over the framework's own import-time check.

    Cheap, and it is the rule an editor is most likely to break by adding an
    option to the control and forgetting the definition.
    """
    for setting in catalogue:
        if setting.data_type is DataType.ENUM:
            assert setting.options, setting.key
            assert setting.default in setting.options, setting.key
