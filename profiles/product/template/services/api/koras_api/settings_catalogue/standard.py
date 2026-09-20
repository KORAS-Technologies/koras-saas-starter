"""The settings every KORAS product has.

Thirty-two definitions in seven categories. A product adds its own in
`product.py` beside this file; nothing here has to change for it to.

**What is consumed today, as of 2026-09-19.** `general.language` is read by the
locale resolver. `KorasDataTable` reads five of the ten `grid.*` settings:
`pageSize`, `pageSizeOptions`, `paginationEnabled`, `stickyHeader` and
`rowDensity`. The other five are declared and read by nothing --
`allowColumnResize` and `allowColumnReorder` need interactions that component
does not have, and the three `remember*` settings describe persistence of state
a table does not own. Everything else here is declared, validated, stored,
audited and rendered on the settings pages, and no other code reads it.

A setting nothing reads is still worth declaring: it is one definition and three
translations, and a product that needs it does not have to design it. A setting
a component *reads and ignores* is not -- that teaches people the whole
framework is decorative -- which is why the five above are absent from
`data-table.tsx` rather than wired to nothing.

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
    surfaced: bool = True,
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
        org_admin_visible=org_admin_visible and surfaced,
        # A person is offered exactly what a person may write. The definition
        # refuses the other combination outright, so this cannot drift.
        #
        # `surfaced` is the second half: a setting nothing honours yet is
        # published in the catalogue -- a product may read it -- and shown on
        # neither customer page. A control that visibly does nothing teaches
        # people the whole framework is decorative, which is a more expensive
        # lesson than a missing row on a settings page.
        user_visible=scope.admits_user and surfaced,
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
        # A number, not a select, and it was a select until 2026-09-19. An
        # INTEGER has no `options`, the form's select renders `field.options`,
        # and the result was an empty dropdown that displayed nothing and
        # submitted nothing -- so the one setting this framework was built to
        # demonstrate could not be changed from either page. The comment above
        # says "with the five options below", and nothing ever read them into
        # the control. `grid.pageSizeOptions` still decides what a *table's*
        # own pager offers, which is where it is read.
        ui=UiControl.NUMBER,
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
        # Honoured since 2026-09-19: the shared table draws a resize
        # handle on every column a caller has not marked `fixed`. The
        # width is a per-viewer, per-device convenience and lives in
        # browser storage; `grid.rememberColumns` decides whether it
        # outlives the page.
    ),
    _setting(
        "grid.allowColumnReorder",
        Category.GRID,
        DataType.BOOLEAN,
        False,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=60,
        # Honoured since 2026-09-19, as two buttons per header rather
        # than a drag: a drag is invisible to a keyboard and awkward on
        # a touch screen. A column marked `fixed` by its caller stays
        # where it is whatever this says.
    ),
    _setting(
        "grid.rememberFilters",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=70,
        # Declared, and honoured by nothing as of 2026-09-19.
        surfaced=False,
    ),
    _setting(
        "grid.rememberSort",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=80,
        # Declared, and honoured by nothing as of 2026-09-19.
        surfaced=False,
    ),
    _setting(
        "grid.rememberColumns",
        Category.GRID,
        DataType.BOOLEAN,
        True,
        Scope.GLOBAL_ORG_USER,
        ui=UiControl.TOGGLE,
        order=90,
        # Honoured since 2026-09-19. It decides *whether* an
        # arrangement is kept, not what was arranged: where somebody
        # dragged a column is per viewer, per table and per device, so
        # it lives in browser storage rather than in a settings row per
        # table per person that nobody could read.
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
    #
    # All three were surfaced and read by nothing at all from the day the
    # framework shipped until 2026-09-19, which is the failure `surfaced` was
    # introduced to prevent, four days later and in the same file. A customer
    # could switch off notification emails and still receive them.
    #
    # The first is honoured now: the dashboard layout reads it and does not
    # draw the bell, and the notification centre says why it is empty. The
    # other two are unsurfaced until the channel seam and the digest job exist,
    # because a control that changes nothing is worse than one that is not
    # offered.
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
        # **Organisation, not person**, and the narrowing is a decision rather
        # than an oversight. A mail goes to an *address*; the product learns
        # its members' addresses from the platform's member list, which carries
        # an email and a role and **not** the ZITADEL subject. So a recipient
        # the product can mail is a recipient it cannot match to a member, and
        # a person-level switch on this setting would be a control that nothing
        # could ever read. That is precisely the failure `surfaced=False` was
        # introduced to prevent, and hiding it would have been the same mistake
        # in a different place -- the honest fix is not to offer the rung.
        #
        # It becomes `GLOBAL_ORG_USER` the day the platform answers a subject
        # beside the address. F26 in `docs/FOLLOW_UPS.md`.
        Scope.GLOBAL_ORG,
        ui=UiControl.TOGGLE,
        order=20,
        # Surfaced again on 2026-09-19, when CAT-01 Phase 2 moved the one mail
        # a product sends onto the dispatch point. `core/dispatch.py` resolves
        # it through the settings resolver -- the same code the settings page
        # displays -- so an organisation switching it off switches it off.
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
        # Declared, and honoured by nothing as of 2026-09-19: there is no
        # digest job, and Phase 2 deliberately did not build one -- a digest
        # needs an outbox to accumulate into, which is Phase 3. CAT-01 Phase 4.
        surfaced=False,
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
        # Declared, and honoured by nothing as of 2026-09-19 -- unlike the
        # other two files settings, which the presign route now enforces.
        # There is nothing here to honour it *on*: the upload route mints
        # one ticket for one file and the browser sends them one at a time,
        # so a limit on how many go at once has no moment to apply. It is
        # unsurfaced until a multi-file upload exists rather than left
        # offering a number nothing reads.
        surfaced=False,
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
