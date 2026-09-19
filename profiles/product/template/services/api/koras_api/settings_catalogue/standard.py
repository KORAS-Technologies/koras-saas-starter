"""The settings every KORAS product has.

Thirty-two definitions in seven categories. A product adds its own in
`product.py` beside this file; nothing here has to change for it to.

**What is consumed today, as of 2026-09-17.** `general.language` is read by the
locale resolver, and the ten `grid.*` settings are read by the shared table
component. The rest are declared, validated, stored, audited and rendered on
the settings pages, and no other code reads them yet -- they are the vocabulary
a product is expected to consume, and each one is consumed by the surface that
owns it rather than by this package. A setting that nothing reads is still
worth declaring: it is one definition and three translations, and a product
that needs it does not have to design it.

**The scopes are not decoration.** A setting is `GLOBAL_ORG_USER` when one
person disagreeing with their colleagues harms nobody -- a theme, a date
format, how many rows they like -- and `GLOBAL_ORG` when it is a policy the
organisation holds: what may be uploaded, how large, which currency the money
is in. Getting that wrong is how an upload limit becomes something each person
sets for themselves.
"""

from __future__ import annotations

from koras_settings import Category, DataType, Scope, SettingDefinition, Status, UiControl

#: The languages a stored value may name.
#:
#: The same list `routers/tenant.py` holds as `SUPPORTED_LOCALES` and
#: `packages/i18n` holds as its own -- what the frontend can *speak*, as
#: distinct from what a product *offers*. Duplicated because the two runtimes
#: cannot import each other, and kept level by the generator's structural test,
#: the same way the permission catalogue is.
LOCALES: tuple[str, ...] = ("en", "de", "es")

#: What `general.language` offers: the catalogues, and letting the browser decide.
#:
#: **`auto` is why seeding this setting does not break language negotiation.**
#: Every organisation-scoped setting gets a row at provisioning, holding the
#: definition's default -- that is the snapshot, and it is what stops a platform
#: change reaching a tenant that already exists. For every other setting the
#: default is a real value and seeding it changes nothing.
#:
#: Language was the exception. A request resolves its language from the stored
#: choice, then the cookie, then the tenant's default, then `Accept-Language`,
#: then the product's own -- and a seeded default of `en` would sit in the third
#: position for every tenant, so a German browser would be answered in English
#: and the fourth step would never run again.
#:
#: The fix is to make "no opinion" a value somebody can hold rather than an
#: absence that seeding destroys. `auto` is that value; the API maps it back to
#: null, and the chain behaves exactly as it did. It is also better than the
#: absence was: a person can now *choose* to follow their browser, which
#: previously meant clearing a preference they could not see.
#:
#: The same shape `ui.theme` already has with `system`.
LANGUAGE_OPTIONS: tuple[str, ...] = ("auto", *LOCALES)


def _setting(
    key: str,
    category: Category,
    data_type: DataType,
    default: object,
    scope: Scope,
    *,
    ui: UiControl,
    order: int,
    options: tuple[str, ...] = (),
    minimum: float | None = None,
    maximum: float | None = None,
    org_admin_visible: bool = True,
    status: Status = Status.AVAILABLE,
) -> SettingDefinition:
    """One definition, with the two i18n keys derived from the setting's own.

    Derived rather than passed, because a label key that can disagree with its
    setting is a label key that eventually does. `settings.def.<key>.label` and
    `.description` is the shape, and the generator's test asserts every one of
    them exists in every catalogue.
    """
    return SettingDefinition(
        key=key,
        category=category,
        data_type=data_type,
        default=default,  # type: ignore[arg-type]
        scope=scope,
        label_key=f"settings.def.{key}.label",
        description_key=f"settings.def.{key}.description",
        options=options,
        minimum=minimum,
        maximum=maximum,
        org_admin_visible=org_admin_visible,
        # A person is offered exactly what a person may write. The definition
        # refuses the other combination outright, so this cannot drift.
        user_visible=scope.admits_user,
        status=status,
        ui=ui,
        order=order,
    )


SETTINGS: list[SettingDefinition] = [
    # ── General ──────────────────────────────────────────────────────────────
    _setting(
        "general.timezone",
        Category.GENERAL,
        DataType.STRING,
        "UTC",
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TEXT,
        order=10,
    ),
    # The language work (FOLLOW_UPS F20) stored this on `tenant_settings` and
    # `member_preferences`. It is the same value at the same two levels, and
    # migration `00031` moves it here so there is one answer to "what language
    # does this person want" rather than two that can disagree.
    #
    # Defaults to `auto`, not to a language. See `LANGUAGE_OPTIONS`.
    _setting(
        "general.language",
        Category.GENERAL,
        DataType.ENUM,
        "auto",
        Scope.GLOBAL_ORG_USER,
        options=LANGUAGE_OPTIONS,
        ui=UiControl.SELECT,
        order=20,
    ),
    _setting(
        "general.dateFormat",
        Category.GENERAL,
        DataType.ENUM,
        "iso",
        Scope.GLOBAL_ORG_USER,
        options=("iso", "dmy", "mdy", "long"),
        ui=UiControl.SELECT,
        order=30,
    ),
    _setting(
        "general.timeFormat",
        Category.GENERAL,
        DataType.ENUM,
        "24h",
        Scope.GLOBAL_ORG_USER,
        options=("12h", "24h"),
        ui=UiControl.SELECT,
        order=40,
    ),
    # An organisation's, not a person's. Two colleagues reading one invoice in
    # two currencies is a support ticket, not a preference.
    _setting(
        "general.currency",
        Category.GENERAL,
        DataType.ENUM,
        "EUR",
        Scope.GLOBAL_ORG,
        options=("EUR", "GBP", "USD", "CHF", "AUD", "CAD"),
        ui=UiControl.SELECT,
        order=50,
    ),
    _setting(
        "general.firstDayOfWeek",
        Category.GENERAL,
        DataType.ENUM,
        "monday",
        Scope.GLOBAL_ORG_USER,
        options=("monday", "sunday", "saturday"),
        ui=UiControl.SELECT,
        order=60,
    ),
    # ── Appearance ───────────────────────────────────────────────────────────
    #
    # `ui.*` rather than `appearance.*`: `ui.theme` is what a reader expects and
    # is what the brief asked for. The key's first segment is conventionally the
    # category and is deliberately not enforced -- see `SettingDefinition`.
    _setting(
        "ui.theme",
        Category.APPEARANCE,
        DataType.ENUM,
        "system",
        Scope.GLOBAL_ORG_USER,
        options=("system", "light", "dark"),
        ui=UiControl.SELECT,
        order=10,
    ),
    _setting(
        "ui.density",
        Category.APPEARANCE,
        DataType.ENUM,
        "comfortable",
        Scope.GLOBAL_ORG_USER,
        options=("comfortable", "compact"),
        ui=UiControl.SELECT,
        order=20,
    ),
    _setting(
        "ui.sidebarCollapsed",
        Category.APPEARANCE,
        DataType.BOOLEAN,
        False,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=30,
    ),
    _setting(
        "ui.defaultLandingPage",
        Category.APPEARANCE,
        DataType.STRING,
        "/dashboard",
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TEXT,
        order=40,
    ),
    # ── Grid ─────────────────────────────────────────────────────────────────
    #
    # The ten the shared table reads. `grid.pageSize` is the one with a number
    # in the brief and it is 50, paging on, with the five options below.
    _setting(
        "grid.pageSize",
        Category.GRID,
        DataType.INTEGER,
        50,
        Scope.GLOBAL_ORG_USER,
        minimum=10,
        maximum=500,
        ui=UiControl.SELECT,
        order=10,
    ),
    # What the page-size control offers, which is the organisation's decision
    # rather than each person's: a person picks from the list, and picking the
    # list is what an administrator does.
    #
    # Strings rather than integers because it is a `STRING_LIST`, and a list of
    # mixed types is a type nothing round-trips cleanly through jsonb and a
    # `<select>`. The component parses them.
    _setting(
        "grid.pageSizeOptions",
        Category.GRID,
        DataType.STRING_LIST,
        ("10", "25", "50", "100", "250"),
        Scope.GLOBAL_ORG,
        ui=UiControl.CHIPS,
        order=20,
    ),
    _setting(
        "grid.paginationEnabled",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=30,
    ),
    _setting(
        "grid.stickyHeader",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=40,
    ),
    _setting(
        "grid.allowColumnResize",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=50,
    ),
    _setting(
        "grid.allowColumnReorder",
        Category.GRID,
        DataType.BOOLEAN,
        False,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=60,
    ),
    _setting(
        "grid.rememberFilters",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=70,
    ),
    _setting(
        "grid.rememberSort",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=80,
    ),
    _setting(
        "grid.rememberColumns",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=90,
    ),
    _setting(
        "grid.rowDensity",
        Category.GRID,
        DataType.ENUM,
        "comfortable",
        Scope.GLOBAL_ORG_USER,
        options=("comfortable", "compact"),
        ui=UiControl.SELECT,
        order=100,
    ),
    # ── Notifications ────────────────────────────────────────────────────────
    _setting(
        "notifications.inAppEnabled",
        Category.NOTIFICATIONS,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=10,
    ),
    _setting(
        "notifications.emailEnabled",
        Category.NOTIFICATIONS,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=20,
    ),
    _setting(
        "notifications.digestFrequency",
        Category.NOTIFICATIONS,
        DataType.ENUM,
        "weekly",
        Scope.GLOBAL_ORG_USER,
        options=("never", "daily", "weekly"),
        ui=UiControl.SELECT,
        order=30,
    ),
    # ── Files ────────────────────────────────────────────────────────────────
    #
    # Three limits and one preference, and the split is the point: what may be
    # uploaded and how much of it is the organisation's policy, and whether you
    # personally want a preview is not.
    _setting(
        "files.maxUploadSizeMb",
        Category.FILES,
        DataType.INTEGER,
        100,
        Scope.GLOBAL_ORG,
        minimum=1,
        maximum=5120,
        ui=UiControl.NUMBER,
        order=10,
    ),
    _setting(
        "files.allowedExtensions",
        Category.FILES,
        DataType.STRING_LIST,
        ("pdf", "png", "jpg", "jpeg", "csv", "xlsx", "docx", "txt"),
        Scope.GLOBAL_ORG,
        ui=UiControl.CHIPS,
        order=20,
    ),
    _setting(
        "files.maxFilesPerUpload",
        Category.FILES,
        DataType.INTEGER,
        10,
        Scope.GLOBAL_ORG,
        minimum=1,
        maximum=100,
        ui=UiControl.NUMBER,
        order=30,
    ),
    _setting(
        "files.previewEnabled",
        Category.FILES,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=40,
    ),
    # ── Reporting ────────────────────────────────────────────────────────────
    #
    # `last30` matches `koras_reporting.filters.DEFAULT_RANGE_DAYS`, and the
    # export formats are the three `ExportFormat` offers. Both are duplicated
    # here as strings rather than imported, because this catalogue is declared
    # in every product and the reporting package is generated only with the
    # `reporting` capability -- importing it would make a foundation module fail
    # to import in a product that has no analytics.
    _setting(
        "reporting.defaultDateRange",
        Category.REPORTING,
        DataType.ENUM,
        "last30",
        Scope.GLOBAL_ORG_USER,
        options=("last7", "last30", "last90", "lastYear"),
        ui=UiControl.SELECT,
        order=10,
    ),
    _setting(
        "reporting.defaultExportFormat",
        Category.REPORTING,
        DataType.ENUM,
        "csv",
        Scope.GLOBAL_ORG_USER,
        options=("csv", "xlsx", "pdf"),
        ui=UiControl.SELECT,
        order=20,
    ),
    # ── Accessibility ────────────────────────────────────────────────────────
    #
    # Every one of these is a person's, always. An organisation may set a
    # default -- a call centre on small screens, say -- and nobody may be
    # prevented from turning motion off for themselves.
    _setting(
        "accessibility.reducedMotion",
        Category.ACCESSIBILITY,
        DataType.BOOLEAN,
        False,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=10,
    ),
    _setting(
        "accessibility.highContrast",
        Category.ACCESSIBILITY,
        DataType.BOOLEAN,
        False,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=20,
    ),
    _setting(
        "accessibility.fontScale",
        Category.ACCESSIBILITY,
        DataType.DECIMAL,
        1.0,
        Scope.GLOBAL_ORG_USER,
        minimum=0.8,
        maximum=2.0,
        ui=UiControl.NUMBER,
        order=30,
    ),
]
