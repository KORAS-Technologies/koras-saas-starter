import type { en } from './en.js'

/**
 * Spanish.
 *
 * Neutral rather than regional: "usted" throughout, no vocabulary that belongs
 * to one country, so the one catalogue serves Spain and Latin America alike.
 * Typed against the English catalogue like every other; the placeholders and
 * inline tags are the same vocabulary and must be carried over.
 */
export const es: Readonly<Record<keyof typeof en, string>> = {
  /* ---------------------------------------------------------------- common */
  'common.skipToMain': 'Saltar al contenido principal',
  'common.signIn': 'Iniciar sesión',
  'common.getStarted': 'Empezar',
  'common.goToDashboard': 'Ir al panel',
  'common.none': 'Ninguno',
  'common.language': 'Idioma',
  'common.copyright': '© {year} {product}',

  /* --------------------------------------------------- authenticated shell */
  'shell.openNavigation': 'Abrir la navegación',
  'shell.closeNavigation': 'Cerrar la navegación',
  'shell.expandSidebar': 'Expandir la barra lateral',
  'shell.collapseSidebar': 'Contraer la barra lateral',
  'shell.productNavigation': 'Navegación del producto',
  'shell.navigationLabel': 'Producto',
  'shell.drawerNavigationLabel': 'Producto, menú',
  'shell.workspace': 'Espacio de trabajo: ',
  'shell.accountMenu': 'Menú de la cuenta',
  'shell.signedIn': 'Sesión iniciada',
  'shell.manageSubscription': 'Gestionar la suscripción',
  'shell.opensPortal': '(abre el portal de cuentas de Koras)',
  'shell.signOut': 'Cerrar sesión',
  'shell.appearance': 'Apariencia',
  'shell.themeLight': 'Claro',
  'shell.themeSystem': 'Sistema',
  'shell.themeDark': 'Oscuro',
  'shell.lockedPlan': 'No incluido en su plan',
  'shell.lockedUnresolved': 'No se ha podido leer su plan en este momento',
  'subscription.trial.endsIn': 'Su prueba gratuita termina en {days} días.',
  'subscription.trial.endsToday': 'Su prueba gratuita termina hoy.',
  'subscription.trial.open': 'Está en una prueba gratuita.',
  'subscription.trial.addCard': 'Añadir un método de pago',
  'subscription.pastDue.graceDays':
    'Su último pago no se ha completado. El acceso continúa durante {days} días mientras se actualiza la tarjeta.',
  'subscription.pastDue.open':
    'Su último pago no se ha completado. Actualice su método de pago para conservar el acceso.',
  'subscription.pastDue.fixCard': 'Actualizar el método de pago',
  'subscription.closed.trialTitle': 'Su prueba gratuita ha terminado',
  'subscription.closed.title': 'Su suscripción ha terminado',
  'subscription.closed.descriptionAdmin':
    'Sus datos se conservan y no se pierde nada. Elija un plan para continuar donde lo dejó en {product}.',
  'subscription.closed.descriptionMember':
    'Sus datos se conservan y no se pierde nada. Un administrador de su organización puede elegir un plan para reabrir {product}.',
  'subscription.closed.action': 'Elegir un plan',

  'pricing.monthly': 'Mensual',
  'pricing.yearly': 'Anual',
  'pricing.billing': 'Periodo de facturación',
  'pricing.perSeatMonth': 'por puesto y mes',
  'pricing.perSeatYear': 'por puesto y año',
  'pricing.choose': 'Empezar la prueba gratuita',
  'pricing.priceAtCheckout': 'Precio al pagar',
  'pricing.seatsRange': 'De {min} a {max} puestos',
  'pricing.seatsFrom': 'Desde {min} puestos',
  'pricing.singleSeat': 'Cualquier número de puestos',
  'pricing.custom': 'Precio a medida',
  'pricing.contactSales': 'Hablar con ventas',
  'pricing.noTrial': 'Sin prueba gratuita. Se acuerda con nuestro equipo, en sus condiciones.',
  'pricing.contactSubject': '{product}: un plan para nuestra organización',
  'shell.lockedFeature': 'No activado para su organización',
  'shell.roleAdministrator': 'Administrador',
  'shell.roleMember': 'Miembro',

  'accessDenied.title': 'No tiene acceso a esta página',
  'accessDenied.description':
    'Su sesión está iniciada, pero su cuenta no tiene permiso para esta área. Un administrador de su organización puede cambiarlo.',

  /* ------------------------------------------------------- public header */
  'header.primary': 'Principal',
  'header.primarySmall': 'Principal, pantalla pequeña',
  'header.openMenu': 'Abrir el menú',
  'header.closeMenu': 'Cerrar el menú',
  'footer.builtBy': 'Desarrollado por',
  'footer.on': '{product} en {network}',

  /* ------------------------------------------------- the drawn app frame */
  'appFrame.workspace': 'espacio de trabajo',
  'appFrame.overview': 'Resumen de operaciones',
  'appFrame.open': 'Abiertos',
  'appFrame.dueToday': 'Vencen hoy',
  'appFrame.blocked': 'Bloqueados',
  'appFrame.inProgress': 'En curso',
  'appFrame.waiting': 'En espera',
  'appFrame.scheduled': 'Programado',
  'appFrame.row.onboarding': 'Incorporación · Northwind',
  'appFrame.row.renewal': 'Revisión de renovación · Contoso',
  'appFrame.row.access': 'Solicitud de acceso · Fabrikam',
  'appFrame.row.export': 'Exportación trimestral',

  /* -------------------------------------------------------------- sign-in */
  'login.title': 'Iniciar sesión',
  'login.heading': 'Iniciar sesión en {product}',
  'login.description':
    'Le llevaremos al inicio de sesión de su organización y le traeremos de vuelta directamente.',
  'login.noAccount': '¿Aún no tiene cuenta?',
  'login.signedOut.heading': 'Ha cerrado la sesión',
  'login.signedOut.description': 'Vuelva a iniciar sesión cuando lo desee.',
  'login.note':
    'El inicio de sesión usa la cuenta de su organización. No hay una contraseña separada de {product} que recordar ni restablecer.',

  'signIn.description':
    'Use la dirección de correo electrónico y la contraseña de su cuenta de {product}.',
  'signIn.form.email': 'Dirección de correo electrónico',
  'signIn.form.password': 'Contraseña',
  'signIn.form.submit': 'Iniciar sesión',
  'signIn.form.submitting': 'Iniciando sesión…',
  'signIn.form.emailRequired': 'Introduzca su dirección de correo electrónico.',
  'signIn.form.passwordRequired': 'Introduzca su contraseña.',
  'signIn.form.forgot': '¿Ha olvidado su contraseña?',
  'signIn.refused': 'La dirección de correo electrónico o la contraseña no son correctas.',
  'signIn.continuing': 'Sesión iniciada. Le llevamos a la aplicación…',
  'signIn.continue': 'Continuar',
  'signIn.expired': 'Este inicio de sesión ha caducado. Empiece de nuevo.',
  'signIn.startAgain': 'Empezar de nuevo',
  'signIn.tooMany': 'Demasiados intentos desde aquí. Inténtelo de nuevo en unos minutos.',
  'signIn.unavailable':
    'El inicio de sesión no está disponible ahora mismo. Inténtelo de nuevo en breve.',
  'signIn.factor.heading': 'Introduzca su código',
  'signIn.factor.description':
    'Abra su aplicación de autenticación e introduzca el código de seis dígitos que muestra.',
  'signIn.factor.code': 'Código',
  'signIn.factor.submit': 'Continuar',
  'signIn.factor.submitting': 'Comprobando…',
  'signIn.factor.refused': 'El código no es correcto.',
  'signIn.factor.codeRequired': 'Introduzca el código de su aplicación de autenticación.',
  'signIn.provider.or': 'o',
  'signIn.provider.continueWith': 'Continuar con {provider}',
  'signIn.provider.failed':
    'El inicio de sesión con ese proveedor no se completó. Inténtelo de nuevo o inicie sesión con su contraseña.',
  'signIn.provider.notMember':
    'Ninguna cuenta de {product} usa esa dirección de correo electrónico. Pida a su organización que le invite o inicie sesión con su contraseña.',
  'signIn.provider.unverified':
    'Ese proveedor no ha verificado su dirección de correo electrónico. Inicie sesión con su contraseña.',
  'signIn.provider.ambiguous':
    'Esa dirección de correo electrónico pertenece a más de una cuenta. Inicie sesión con su contraseña.',

  /* ------------------------------------------------------ forgot password */
  'forgot.title': 'Contraseña olvidada',
  'forgot.heading': 'Restablecer su contraseña',
  'forgot.description':
    'Introduzca la dirección de correo electrónico con la que inicia sesión. Si pertenece a una cuenta de {product}, le enviaremos un enlace para establecer una nueva contraseña.',
  'forgot.form.email': 'Dirección de correo electrónico',
  'forgot.form.emailRequired': 'Introduzca su dirección de correo electrónico.',
  'forgot.form.emailInvalid': 'Eso no parece una dirección de correo electrónico.',
  'forgot.form.submit': 'Enviar el enlace',
  'forgot.form.submitting': 'Enviando…',
  'forgot.sent.title': 'Revise su correo electrónico',
  'forgot.sent.description':
    'Si {email} pertenece a una cuenta de {product}, un enlace para establecer una nueva contraseña está en camino. Funciona durante 7 días y una sola vez.',
  'forgot.back': 'Volver al inicio de sesión',
  'forgot.tooMany': 'Demasiadas solicitudes desde aquí. Inténtelo de nuevo dentro de una hora.',
  'forgot.unavailable':
    'El restablecimiento de la contraseña no está disponible ahora mismo. Inténtelo de nuevo en breve.',

  /* --------------------------------------------------------------- signup */
  'signup.title': 'Empezar',
  'signup.heading': 'Empezar con {product}',
  'signup.description':
    'Díganos dónde enviar su enlace de confirmación. No se crea nada hasta que lo abra.',
  'signup.haveAccount': '¿Ya tiene una cuenta?',
  'signup.form.organisation': 'Organización',
  'signup.form.email': 'Correo electrónico de trabajo',
  'signup.form.name': 'Su nombre',
  'signup.form.optional': 'Opcional.',
  'signup.form.plan': 'Plan',
  'signup.form.interval': 'Facturación',
  'signup.form.interval.month': 'Mensual',
  'signup.form.interval.year': 'Anual',
  'signup.form.seats': 'Puestos',
  'signup.form.seatsHint': 'Entre {min} y {max}. Podrá cambiarlo más adelante.',
  'signup.form.seatsHintMin': 'Al menos {min}. Podrá cambiarlo más adelante.',
  'signup.form.noteCard':
    'Le enviaremos un enlace para confirmar la dirección y después le pediremos una tarjeta. No se cobra nada hasta que termine su prueba de 14 días.',
  'signup.form.submit': 'Crear cuenta',
  'signup.form.submitting': 'Creando su cuenta',
  'signup.form.note':
    'Le enviaremos por correo un enlace para confirmar la dirección. No se crea nada hasta que lo abra.',
  'signup.sent.title': 'Revise su correo electrónico',
  'signup.sent.message':
    'Busque en {email} un enlace para confirmar su dirección. No se crea nada hasta que lo haga.',
  'signup.error.tooMany': 'Demasiados intentos desde aquí. Inténtelo de nuevo en breve.',
  'signup.error.planUnavailable':
    'Ese plan no está disponible para contratarlo en línea. Póngase en contacto con nosotros.',
  'signup.error.checkDetails': 'Compruebe los datos e inténtelo de nuevo.',
  'signup.error.generic': 'Algo ha fallado. Inténtelo de nuevo.',
  'signup.error.email': 'Introduzca su dirección de correo electrónico.',
  'signup.error.organisation': '¿Cómo se llama su organización?',
  'signup.error.notAvailable': 'El registro no está disponible en este momento.',
  'signup.error.notConfigured':
    'El registro aún no está disponible. Póngase en contacto con nosotros.',
  'signup.error.unreachable': 'No hemos podido conectar con el servicio de registro.',
  'signup.error.seats': 'Elija entre {min} y {max} puestos.',
  'signup.error.seatsMin': 'Elija al menos {min} puestos.',
  'signup.error.interval': 'Ese plan no se vende así. Elija otra opción de facturación.',

  'checkout.title': 'Añadir un método de pago',
  'checkout.description':
    'Su dirección está confirmada. Añada una tarjeta para empezar su prueba de 14 días de {product}.',
  'checkout.opening': 'Le llevamos al pago seguro…',
  'checkout.open': 'Continuar al pago',
  'checkout.trialNote': 'No se cobra nada hasta que termine la prueba, y puede cancelar antes.',
  'checkout.closed.title': 'El pago se ha cerrado',
  'checkout.closed.description':
    'No se ha cobrado nada ni se ha creado nada. Continúe al pago para retomarlo donde lo dejó, o vuelva más tarde: le enviaremos un enlace.',
  'checkout.failed.title': 'No se ha podido abrir el pago',
  'checkout.failed.description':
    'Inténtelo de nuevo en un momento. Su dirección está confirmada y no se pierde nada: le enviaremos un enlace que lo abre.',

  'requestAccess.heading': 'Empezar con {product}',
  'requestAccess.byAdmin':
    'El acceso a {product} lo gestiona el administrador de su organización, no se obtiene en línea. Si usted es el administrador, póngase en contacto con quien opera {product} para su organización.',
  'requestAccess.withContact':
    'Las cuentas de {product} se configuran junto con usted, no por su cuenta. Cuéntenos un poco sobre su organización y le pondremos en marcha.',
  'requestAccess.button': 'Solicitar acceso',
  'requestAccess.subject': 'Acceso a {product}',

  'invitation.heading': '{product} es solo por invitación',
  'invitation.description':
    'Las nuevas organizaciones se unen a {product} por invitación. Si alguien le ha invitado, el enlace de su correo es la vía de entrada; esta página no puede crear la cuenta por usted.',
  'invitation.ask': 'Preguntar por una invitación',
  'invitation.byAdmin': 'Las invitaciones las emite el administrador de su organización.',
  'invitation.subject': 'Invitación a {product}',

  'verify.title': 'Confirme su correo electrónico',
  'verify.incomplete.title': 'Este enlace está incompleto',
  'verify.incomplete.description': 'Abra de nuevo el enlace de su correo o empiece de nuevo.',
  'verify.incomplete.startOver': 'Empezar de nuevo',
  'verify.rateLimited.title': 'Demasiados intentos',
  'verify.rateLimited.description':
    'Su enlace sigue siendo válido. Espere unos minutos y ábralo de nuevo; no empiece de nuevo, no servirá.',
  'verify.invalid.title': 'Este enlace no es válido',
  'verify.invalid.description':
    'Puede que ya se haya usado o que haya caducado. Regístrese de nuevo para obtener uno nuevo.',
  'verify.invalid.again': 'Registrarse de nuevo',

  // ── /activate ───────────────────────────────────────────────────────────────
  'activate.title': 'Establecer contraseña',
  'activate.heading': 'Bienvenido a {product}',
  'activate.description':
    'Establezca una contraseña para {email} para terminar de configurar {organization}.',
  'activate.form.password': 'Contraseña',
  'activate.form.hint': 'Al menos 8 caracteres. Su organización puede exigir más.',
  'activate.form.confirm': 'Confirmar contraseña',
  'activate.form.tooShort': 'Use al menos 8 caracteres.',
  'activate.form.mismatch': 'Las dos contraseñas no coinciden.',
  'activate.form.submit': 'Establecer contraseña y continuar',
  'activate.form.submitting': 'Estableciendo su contraseña…',
  'activate.done.title': 'Su contraseña está establecida',
  'activate.done.description':
    'Inicie sesión con su dirección de correo y la contraseña que acaba de elegir.',
  'activate.done.signIn': 'Iniciar sesión',
  'activate.incomplete.title': 'Ese enlace está incompleto',
  'activate.incomplete.description': 'Vuelva a abrir el enlace de su correo de bienvenida.',
  'activate.rateLimited.title': 'Demasiados intentos',
  'activate.rateLimited.description':
    'Espere unos minutos y vuelva a abrir el enlace. No se ha perdido nada.',
  'activate.invalid.title': 'Ese enlace no es válido',
  'activate.invalid.description':
    'Puede que ya se haya usado o que haya caducado. Si ya estableció una contraseña, inicie sesión; si no, use «Olvidé mi contraseña» en la página de inicio de sesión.',
  'activate.failed': 'Algo ha fallado por nuestra parte. Espere un momento y vuelva a intentarlo.',

  'provisioning.ready.title': 'Su espacio de trabajo está listo',
  'provisioning.ready.description': 'Le llevamos a {product} para iniciar sesión.',
  'provisioning.ready.redirecting': 'Redirigiendo…',
  'provisioning.ready.continue': 'Continuar al inicio de sesión',
  'provisioning.failed.title': 'No hemos podido terminar de configurar su espacio de trabajo',
  'provisioning.failed.description':
    'Su correo está confirmado y no se ha perdido nada. Alguien tiene que revisar esto antes de que pueda iniciar sesión.',
  'provisioning.failed.descriptionContact':
    'Su correo está confirmado y no se ha perdido nada. Alguien tiene que revisar esto antes de que pueda iniciar sesión, y nos gustaría saber de usted.',
  'provisioning.failed.getInTouch': 'Contactar',
  'provisioning.failed.subject': 'Configuración de {product}',
  'provisioning.slow.title': 'Esto está tardando más de lo habitual',
  'provisioning.slow.description':
    'Su cuenta se sigue configurando. Le escribiremos en cuanto esté lista; puede cerrar esta página.',
  'provisioning.waiting.title': 'Configurando su espacio de trabajo',
  'provisioning.waiting.description':
    'Estamos creando <strong>{slug}</strong> en {product}. Suele tardar uno o dos minutos.',
  'provisioning.waiting.descriptionNoSlug':
    'Estamos creando su espacio de trabajo en {product}. Suele tardar uno o dos minutos.',
  'provisioning.waiting.status':
    'Configurando su organización, su cuenta y su espacio de trabajo.',
  'provisioning.waiting.close': 'Puede cerrar esta página; le escribiremos cuando esté listo.',

  'notFound.title': 'No encontramos esa página',
  'notFound.description': 'Puede que el enlace esté desactualizado o que la página se haya movido.',
  'notFound.home': 'Ir a la página de inicio',

  /* ------------------------------------------------------------ dashboard */
  'dashboard.welcome': 'Bienvenido a {product}',
  'dashboard.intro':
    'Ha iniciado sesión. Este es el punto de partida de {product}; la primera pantalla que construya su equipo sustituirá a esta.',
  'dashboard.start.title': 'Por dónde empezar',
  'dashboard.start.build':
    'Construya esta página en <code>apps/web/src/app/dashboard</code>. Todo lo que añada a su lado está protegido por defecto, vive dentro del marco del producto y hereda la marca de este cliente.',
  'dashboard.start.sidebar':
    'Dé a una nueva área un lugar en la barra lateral añadiendo un módulo a <code>navigation</code> en <code>packages/branding/src/index.ts</code>. Nada cambia en el marco; la misma entrada es la que protege la ruta.',
  'dashboard.start.config':
    'El sitio público, su contenido, los colores de este producto y los idiomas que ofrece se configuran en el mismo archivo.',
  'dashboard.start.branding':
    'Los colores de un cliente llegan a través de <code>apps/web/src/lib/tenant-branding.ts</code>, leídos de lo que definió en el portal de la plataforma y superpuestos a la configuración de inquilino de este producto.',

  'insights.title': 'Análisis',
  'insights.notInPlan': 'Análisis no forma parte de su plan. Hable con nosotros para añadirlo.',

  /* ------------------------------------------------------------ analytics */
  'analytics.title': 'Analíticas',
  'analytics.unresolved':
    'No se ha podido leer su plan desde la plataforma KORAS en este momento, así que solo se muestran los informes que incluyen todos los planes. El motivo está en el registro del servidor de esta instalación.',
  'analytics.notIncluded.title': 'No incluido en su plan',
  'analytics.notIncluded.description':
    'Las analíticas forman parte de un plan superior. Su plan actual es <strong>{plan}</strong>. Un administrador de su organización puede cambiar el plan en el portal de la cuenta.',
  'analytics.notIncluded.notRecorded': 'no registrado',
  'analytics.of': '{used} de {limit}',
  'analytics.previousPeriod': 'respecto al periodo anterior',
  'analytics.trend.up': 'Sube',
  'analytics.trend.down': 'Baja',
  'analytics.trend.unchanged': 'Sin cambios',
  'analytics.kind.estimated': 'Estimado',
  'analytics.kind.derived': 'Derivado',
  'analytics.kind.unavailable': 'No disponible',
  'analytics.chart.asTable': 'Mostrar como tabla',
  'analytics.chart.noData': 'Nada en este periodo.',
  'analytics.chart.value': 'Valor',
  'analytics.chart.period': 'Periodo',
  'analytics.table.empty': 'No hay nada que mostrar para este periodo.',
  'analytics.table.truncated':
    'Solo se muestran las primeras filas. Acote el periodo para verlo todo.',
  'analytics.filters.period': 'Periodo',
  'analytics.filters.from': 'Desde',
  'analytics.filters.to': 'Hasta',
  'analytics.filters.apply': 'Aplicar',
  'analytics.export.download': 'Descargar',
  'analytics.export.notAllowed': 'La descarga no está incluida en su plan o en su rol.',
  'analytics.export.background': 'Preparar en segundo plano',
  'analytics.export.queued':
    'El archivo se está preparando. Aparecerá abajo, en Exportaciones, cuando esté listo.',
  'analytics.export.csv': 'CSV',
  'analytics.export.xlsx': 'Excel',
  'analytics.export.pdf': 'PDF',
  'analytics.schedule.heading': 'Envío programado',
  'analytics.schedule.intro':
    'Reciba este informe por correo de forma periódica. Cada envío cubre el día, la semana o el mes anterior.',
  'analytics.schedule.cadence': 'Frecuencia',
  'analytics.schedule.daily': 'Cada día',
  'analytics.schedule.weekly': 'Cada semana',
  'analytics.schedule.monthly': 'Cada mes',
  'analytics.schedule.format': 'Formato',
  'analytics.schedule.recipients': 'Enviar a',
  'analytics.schedule.recipientsHint': 'Direcciones de correo, separadas por comas. Hasta diez.',
  'analytics.schedule.create': 'Programar',
  'analytics.schedule.remove': 'Quitar',
  'analytics.schedule.empty': 'No hay nada programado para este informe.',
  'analytics.schedule.next': 'Próximo envío',
  'analytics.schedule.notIncluded': 'El envío programado no está incluido en su plan.',
  'analytics.schedule.created': 'La programación se ha creado.',
  'analytics.schedule.removed': 'La programación se ha eliminado.',
  'analytics.schedule.invalid':
    'No se ha podido crear la programación. Revise las direcciones y vuelva a intentarlo.',
  'analytics.exports.heading': 'Exportaciones',
  'analytics.exports.intro': 'Archivos preparados en segundo plano, listos para descargar.',
  'analytics.exports.empty': 'Todavía no hay exportaciones.',
  'analytics.exports.download': 'Descargar',
  'analytics.exports.pending': 'Preparando…',
  'analytics.exports.failed': 'No se ha podido preparar el archivo.',
  'analytics.exports.retention': 'Las exportaciones se conservan {days} días.',
  'analytics.exports.gone': 'Esa exportación ya no está disponible.',
  'analytics.error.format': 'Ese formato no se ofrece para este informe.',
  'analytics.list.heading': 'Informes',
  'analytics.category.overview': 'Resumen',
  'analytics.category.usage': 'Uso',
  'analytics.category.people': 'Personas',
  'analytics.category.billing': 'Facturación',
  'analytics.category.ai': 'IA',
  'analytics.category.activity': 'Actividad',
  'analytics.category.product': 'Este producto',
  'analytics.loading': 'Cargando el informe…',
  'analytics.retry': 'Reintentar',
  'analytics.error.plan': 'Su plan no incluye este informe.',
  'analytics.error.forbidden': 'Su cuenta no puede abrir este informe.',
  'analytics.error.filters': 'Este informe no acepta esos filtros.',
  'analytics.error.export': 'Su plan no incluye la descarga de informes.',
  'analytics.error.unavailable':
    'Las analíticas no están disponibles en este momento. El motivo está en el registro del servidor.',
  'analytics.error.generic': 'Algo ha salido mal. Vuelva a intentarlo.',

  /* ------------------------------------------------------------- settings */
  'settings.title': 'Configuración',
  'settings.intro':
    'Qué es {product}, qué contiene esta instalación y qué incluye el plan de su organización.',
  'settings.product.title': 'Producto',
  'settings.product.name': 'Nombre',
  'settings.product.identifier': 'Identificador',
  'settings.product.tagline': 'Lema',
  'settings.product.configuredIn':
    'Configurado en <code>packages/branding/src/index.ts</code>, donde también se declaran los colores, el logotipo, los idiomas y los módulos de la barra lateral de este producto.',
  'settings.deployment.title': 'Esta instalación',
  'settings.deployment.description':
    'Los componentes con los que se generó este repositorio. Un módulo de la barra lateral que requiera uno ausente se oculta en lugar de romperse, y la lista es fija durante la vida del repositorio: añadir uno significa generar con él.',
  'settings.plan.title': 'Plan',
  'settings.plan.resolved': 'Obtenido de la plataforma KORAS para su organización.',
  'settings.plan.plan': 'Plan',
  'settings.plan.features': 'Funciones incluidas',
  'settings.plan.noneRecorded': 'Ninguno registrado',
  'settings.plan.unavailable':
    'No disponible. No se ha podido leer su plan desde la plataforma KORAS en este momento, así que todo lo condicionado al plan no está disponible hasta que pueda leerse. Nada más del producto se ve afectado, y el motivo está en el registro del servidor de esta instalación.',
  'settings.plan.portalHint':
    'Las suscripciones y la facturación se gestionan en el portal de cuentas de KORAS. Defina <code>product.accountUrl</code> para enlazarlo desde aquí y desde el menú del perfil.',
  'settings.plan.manage': '<a>Gestione su suscripción</a> en el portal de cuentas de KORAS.',
  'settings.language.title': 'Idioma',
  'settings.language.description':
    'El idioma en que se le muestra {product} en este dispositivo. Solo afecta a la interfaz; lo que su organización introduce en el producto se conserva tal como se escribió.',
  'settings.language.label': 'Mostrar {product} en',
  'settings.language.save': 'Cambiar idioma',
  'settings.appearance.title': 'Apariencia',
  'settings.appearance.description':
    'Claro, oscuro o lo que tenga configurado este dispositivo. Se recuerda solo en este navegador.',

  /* ---------------------------------------------------------------- files */
  'files.title': 'Archivos',
  'files.intro':
    'Lo que su organización ha guardado en {product}. Los archivos van directamente desde su navegador al almacenamiento asignado a su organización; el producto mantiene la lista.',
  'files.unresolved':
    'No se ha podido leer su plan desde la plataforma KORAS en este momento, así que no se muestra el límite de almacenamiento. Las subidas siguen funcionando.',
  'files.notIncluded.title': 'No incluido en su plan',
  'files.notIncluded.description':
    'El almacenamiento de archivos forma parte de un plan superior. Su plan actual es <strong>{plan}</strong>. Lo ya guardado se conserva.',
  'files.notIncluded.notRecorded': 'no registrado',
  'files.upload': 'Subir un archivo',
  'files.uploading': 'Subiendo…',
  'files.choose': 'Elegir un archivo para subir',
  'files.download': 'Descargar',
  'files.remove': 'Eliminar',
  'files.confirmRemove': '¿Eliminar {name}? No se puede deshacer.',
  'files.empty': 'Aún no hay nada guardado',
  'files.emptyHint': 'Suba un archivo y aparecerá aquí para todos en su organización.',
  'files.column.name': 'Nombre',
  'files.column.size': 'Tamaño',
  'files.column.uploadedAt': 'Subido',
  'files.column.searchable': 'Asistente',
  'files.searchable.yes': 'Consultable',
  'files.searchable.pending': 'Indexando…',
  'files.searchable.no': 'No consultable',
  'files.searchable.unknown': 'No indexado',
  'files.usage': '{used} de {limit} usados',
  'files.usageUnlimited': '{used} usados',
  'files.usageUnknown': 'Límite de almacenamiento no disponible ahora mismo',
  'files.provider': 'Guardado en {provider}',
  'files.retry': 'Volver a intentarlo',
  'files.error.plan': 'Su plan no incluye esto, o la subida superaría su límite de almacenamiento.',
  'files.error.forbidden': 'Su cuenta no puede hacer eso.',
  'files.error.notArrived': 'El archivo no ha llegado al almacenamiento como se esperaba. Vuelva a intentar la subida.',
  'files.error.unavailable':
    'El almacenamiento de archivos no está disponible para su organización ahora mismo. El motivo está en el registro del servidor.',
  'files.error.generic': 'Algo ha fallado. Vuelva a intentarlo.',

  /* --------------------------------------------------------------- assistant */
  'assistant.title': 'Asistente',
  'assistant.intro':
    'Pregunte sobre aquello en lo que trabaja. El asistente puede leer lo que su organización guarda aquí y proponer acciones, que solo se ejecutan cuando alguien las aprueba.',
  'assistant.unresolved':
    'No se ha podido leer su plan ahora mismo, así que el asistente puede rechazar la petición. Si persiste, avise a un administrador.',
  'assistant.notIncluded.title': 'No incluido en su plan',
  'assistant.notIncluded.description':
    'El asistente no forma parte del plan <strong>{plan}</strong>. Un administrador de su organización puede cambiar el plan en el portal de la cuenta.',
  'assistant.notIncluded.notRecorded': 'sin registrar',
  'assistant.open': 'Abrir el asistente',
  'assistant.close': 'Cerrar el asistente',
  'assistant.drawerTitle': 'Asistente',
  'assistant.newConversation': 'Nueva conversación',
  'assistant.empty': 'Pregunte lo que quiera sobre su organización',
  'assistant.emptyHint': 'El asistente responde a partir de lo que su organización guarda aquí, y de nada más.',
  'assistant.you': 'Usted',
  'assistant.speaker': 'Asistente',
  'assistant.composer.label': 'Su mensaje',
  'assistant.composer.placeholder': 'Pregunte al asistente…',
  'assistant.send': 'Enviar',
  'assistant.sending': 'Pensando…',
  'assistant.retry': 'Volver a intentarlo',
  'assistant.suggestions.title': 'Pruebe a preguntar',
  'assistant.suggestions.files': '¿Qué archivos tenemos?',
  'assistant.suggestions.summary': 'Resume lo que estoy viendo',
  'assistant.usage': '{used} de {limit} peticiones usadas este mes',
  'assistant.usageUnlimited': '{used} peticiones este mes',
  'assistant.usageOverage':
    '{used} peticiones este mes, más allá de las {limit} de su plan. Cargos por uso hasta ahora: ${charges}',
  'assistant.usageUnknown': 'El cupo no está disponible ahora mismo',
  'assistant.citations': 'Fuentes',
  'assistant.activity.title': 'Actividad reciente del asistente',
  'assistant.activity.hint': 'Lo que el asistente propuso, ejecutó, se le rechazó y se decidió, para las personas que aprueban. Nunca el contenido de una conversación.',
  'assistant.activity.empty': 'Aún no hay nada registrado.',
  'assistant.pending.title': 'Pendiente de aprobación',
  'assistant.pending.hint':
    'El asistente lo ha propuesto y no se ejecutará hasta que alguien lo apruebe.',
  'assistant.pending.cannotDecide': 'Un administrador de su organización tiene que decidirlo.',
  'assistant.approve': 'Aprobar',
  'assistant.reject': 'Rechazar',
  'assistant.deciding': 'En curso…',
  'assistant.operation.read': 'Lee',
  'assistant.operation.write': 'Cambia algo',
  'assistant.operation.destructive': 'Elimina algo',
  'assistant.operation.external': 'Sale del producto',
  'assistant.toolResult': 'Resultado de {tool}',
  'assistant.toolResultShow': 'Ver los detalles',
  'assistant.error.plan': 'Su plan no incluye el asistente.',
  'assistant.error.forbidden': 'Su cuenta no puede hacer eso.',
  'assistant.error.limit': 'Su organización ha agotado el cupo del asistente para este mes.',
  'assistant.error.unavailable':
    'El asistente no está disponible ahora mismo. El motivo está en el registro del servidor.',
  'assistant.error.timeout': 'El asistente ha tardado demasiado en responder. Vuelva a intentarlo.',
  'assistant.error.generic': 'Algo ha fallado. Vuelva a intentarlo.',

  /* --------------------------------------------------------- team & access */
  'team.title': 'Equipo y acceso',
  'team.intro':
    'Quién de su organización puede usar {product} y qué puede hacer aquí. Añadir y quitar personas de la propia organización se hace en el portal de cuentas de KORAS; esta página regula solo el acceso a este producto.',
  'team.yours.title': 'Su acceso',
  'team.yours.signedInAs': 'Sesión iniciada como',
  'team.yours.role': 'Rol en este producto',
  'team.yours.orgRoles': 'Roles en la organización',
  'team.yours.permissions': 'Permisos',
  'team.how.title': 'Cómo se decide el acceso',
  'team.how.description':
    'Cada rol de la organización conlleva un conjunto de permisos en este producto. La correspondencia vive en <code>packages/permissions/src/index.ts</code> y es la misma que leen la barra lateral y cada comprobación de ruta: un módulo oculto de la navegación se rechaza en su URL por la misma regla, no solo se omite del menú.',
  'team.how.caption': 'Roles de la organización y los permisos del producto que conlleva cada uno',
  'team.how.colRole': 'Rol en la organización',
  'team.how.colPermissions': 'Permisos en este producto',
  'team.perPerson.title': 'Asignación por persona',
  'team.perPerson.description':
    'Aún no disponible. El acceso a este producto se deriva actualmente del rol de cada persona en la organización, así que cualquiera con un rol en su organización puede abrir {product}. Conceder o revocar el acceso de una sola persona de forma independiente requiere un almacén de asignaciones que este repositorio no tiene; <code>packages/permissions/src/index.ts</code> nombra la única función que cambia cuando llegue.',
  'team.perPerson.manage':
    'Usted tiene <code>team.manage</code>, así que los controles aparecerán aquí para usted cuando existan.',

  /* ----------------------------------------------------- legal page frame */
  'legal.notReviewed.label': 'Aún sin revisar.',
  'legal.notReviewed.text':
    'Esta página describe lo que hace el software. No es un documento legal y no la ha revisado nadie cualificado para redactarlo. Sustitúyala antes de vender este producto y pase <code>reviewed</code> para retirar este aviso.',

  /* -------------------------------------------------------------- privacy */
  'privacy.title': 'Privacidad',
  'privacy.metaDescription': 'Cómo trata {product} los datos personales.',
  'privacy.summary': 'Qué almacena {product} sobre las personas que lo usan, y por qué.',
  'privacy.stored.title': 'Qué se almacena sobre usted',
  'privacy.stored.p1':
    'Al iniciar sesión, {product} registra el identificador que nos da el proveedor de inicio de sesión de su organización, su dirección de correo y su nombre visible. Registra a qué organización pertenece y qué rol tiene en ella, porque esos dos hechos deciden qué puede abrir.',
  'privacy.stored.p2':
    'Todo lo demás en {product} son datos que su propia organización ha puesto ahí. Le pertenecen a ella, no a nosotros.',
  'privacy.who.title': 'Quién puede verlos',
  'privacy.who.p1':
    'Los datos de su organización están separados de los de cualquier otra en la propia base de datos, mediante seguridad a nivel de fila, no mediante un filtro en la aplicación. Una consulta que olvide acotarse no devuelve nada en lugar de registros ajenos.',
  'privacy.who.p2':
    'Las personas que administran {product} pueden acceder a datos en el curso de su operación y soporte. Lo que hacen queda registrado.',
  'privacy.signin.title': 'Inicio de sesión',
  'privacy.signin.p1':
    '{product} nunca ve su contraseña. El inicio de sesión ocurre en el proveedor de identidad de su organización, que solo nos dice quién es usted y qué puede hacer. Su sesión es una cookie que firma esta aplicación, que nadie más puede leer y que solo se envía a este sitio.',
  'privacy.cookies.title': 'Cookies',
  'privacy.cookies.p1':
    'Tres, y todas necesarias: una guarda su sesión, otra lleva el token que esta aplicación reenvía a su propia API y otra recuerda el idioma que eligió. No hay cookies de publicidad ni de análisis en {product} tal como se distribuye.',
  'privacy.ask.title': 'Preguntas sobre sus datos',
  'privacy.ask.contactAdmin': 'Contacte con quien administra {product} en su organización.',
  'privacy.ask.writeTo': 'Escriba a <a>{email}</a>.',

  /* ---------------------------------------------------------------- terms */
  'terms.title': 'Condiciones',
  'terms.metaDescription': 'Las condiciones en las que se proporciona {product}.',
  'terms.summary': 'Qué puede esperar de {product}, y qué se espera de usted.',
  'terms.accounts.title': 'Cuentas',
  'terms.accounts.p1':
    'El acceso a {product} pertenece a una organización, no a una persona. Su organización decide quién puede iniciar sesión y qué puede hacer cada persona; quitar a alguien de la organización le retira el acceso.',
  'terms.accounts.p2':
    'Usted es responsable de lo que ocurra con su inicio de sesión. Avise a su administrador de inmediato si cree que otra persona lo está usando.',
  'terms.plans.title': 'Planes',
  'terms.plans.p1':
    'Lo que su organización puede usar lo decide su plan. Las funciones fuera de él se ocultan o se muestran como no disponibles: nunca se degradan en silencio ni se cobran sin haberse contratado.',
  'terms.plans.p2':
    'Un periodo de prueba termina en su fecha. Cuando lo hace, cesa el acceso a las funciones condicionadas al plan y la cuenta permanece abierta, para que alguien pueda seguir iniciando sesión y elegir un plan.',
  'terms.data.title': 'Sus datos',
  'terms.data.p1':
    'Los datos que su organización introduce en {product} siguen siendo de su organización. Se almacenan separados de los de cualquier otra, y no se usan para entrenar nada ni se venden a nadie.',
  'terms.use.title': 'Uso aceptable',
  'terms.use.p1':
    'No intente acceder a los datos de otra organización, interrumpir el servicio para los demás ni usar {product} para infringir la ley. El acceso puede suspenderse cuando ocurra cualquiera de estas cosas.',
  'terms.changes.title': 'Cambios',
  'terms.changes.p1':
    'Estas condiciones pueden cambiar. Los cambios sustanciales se anuncian antes de entrar en vigor, no se aplican en silencio.',

  /* ------------------------------------------------------------------ FAQ */
  'faq.title': 'Preguntas frecuentes',
  'faq.metaDescription': 'Preguntas habituales sobre {product}.',
  'faq.summary': 'Las preguntas que más se hacen sobre {product}.',
  'faq.signin.title': '¿Cómo inicio sesión?',
  'faq.signin.p1':
    'A través del proveedor de identidad de su organización. {product} nunca pide ni guarda una contraseña: se le envía a iniciar sesión y vuelve aquí. Si su organización exige un segundo factor, se le pedirá y se le rechazará sin él, en lugar de devolverle en bucle a la página de inicio de sesión.',
  'faq.missing.title': '¿Por qué no veo una sección que otros sí ven?',
  'faq.missing.p1': 'Lo deciden cuatro cosas, y fallan de forma distinta a propósito.',
  'faq.missing.p2':
    'Su <strong>rol</strong> decide qué puede hacer; una sección para la que no tiene permiso se oculta y su dirección también se rechaza. El <strong>plan</strong> de su organización decide qué ha comprado; esas secciones no aparecen o aparecen bloqueadas, según si es algo que podría añadir. Los propios <strong>interruptores de funciones</strong> de su organización funcionan igual. Y algunas secciones solo existen en instalaciones generadas con ellas.',
  'faq.missing.p3':
    'Configuración → General nombra el archivo detrás de cada una de las cuatro, que es la forma más rápida de saber con cuál se ha topado.',
  'faq.people.title': '¿Quién puede añadir o quitar personas?',
  'faq.people.p1':
    'Los propietarios y administradores de su organización, en el portal de cuentas de KORAS. Equipo y acceso en {product} muestra quién tiene acceso aquí y qué conlleva cada rol; añadir a alguien a la propia organización se hace en el portal.',
  'faq.trial.title': '¿Qué pasa cuando termina un periodo de prueba?',
  'faq.trial.p1':
    'Las funciones que requieren un plan dejan de estar disponibles y todo lo demás sigue funcionando. La cuenta permanece abierta y puede seguir iniciando sesión: una cuenta que desapareciera con la prueba sería una que nadie podría mejorar.',
  'faq.branding.title': '¿Podemos usar nuestros propios colores y logotipo?',
  'faq.branding.p1':
    'Sí. Un administrador los define para su organización y cada página con sesión los adopta: colores, radio de las esquinas y un logotipo para fondos claros y oscuros. Hasta entonces verá la marca del propio producto.',
  'faq.language.title': '¿Puedo usar {product} en otro idioma?',
  'faq.language.p1':
    'Sí, cuando el producto lo ofrece. El selector de idioma de la cabecera y de Configuración cambia la interfaz para usted en este dispositivo; hasta que elija, se usa la preferencia de idioma de su navegador.',
  'faq.isolation.title': '¿Los datos de mi organización están separados de los de los demás?',
  'faq.isolation.p1':
    'Sí, y están separados en la base de datos, no porque la aplicación recuerde preguntar. Una consulta que no nombre a su organización no devuelve nada en absoluto.',

  // F20 phase 2: persistence and admin
  /* ------------------------------------------------------ language, stored */
  'settings.language.remembered':
    'Como ha iniciado sesión, su elección se guarda en su cuenta y le acompaña en todos los dispositivos en los que inicie sesión.',
  'settings.language.tenantTitle': 'Predeterminado para su organización',
  'settings.language.tenantDescription':
    'Lo que ve un miembro de su organización antes de elegir un idioma por sí mismo. Quien ya ha elegido conserva su elección.',
  'settings.language.tenantLabel': 'Los miembros empiezan en',
  'settings.language.tenantFollowBrowser': 'el idioma de su navegador',
  'settings.language.tenantSave': 'Guardar predeterminado',
  'settings.language.tenantSaving': 'Guardando…',
  'settings.language.tenantSaved': 'Se guardó el idioma predeterminado.',
  'settings.language.tenantError':
    'No se pudo guardar el idioma predeterminado. Inténtelo de nuevo en un momento.',
  'settings.language.tenantForbidden':
    'Solo un propietario o administrador puede cambiar el idioma predeterminado.',

  /* ------------------------------------------------------------- admin */
  'admin.title': '{product} Admin',
  'admin.login.audience':
    'Para propietarios y administradores de la organización. Se requiere autenticación multifactor.',
  'admin.mfaRequired':
    'Se requiere autenticación multifactor. Registre un segundo factor y vuelva a iniciar sesión.',
  'admin.forbidden': 'Esta aplicación es para propietarios y administradores de la organización.',
  'admin.home.signedInAs': 'Sesión iniciada como {name}.',

  /* ------------------------------------------ F20 phase 2: errors and email */
  'restore.title':
    'Restaurar',
  'restore.description':
    'Recuperar un archivo desde su copia de seguridad. Deciden dos personas: una lo solicita y otra lo aprueba. Nada se restaura hasta entonces.',
  'restore.available':
    'Que se puede restaurar',
  'restore.availableDescription':
    'Archivos con copia de seguridad. Un archivo eliminado sigue apareciendo aqui: para eso existe la copia.',
  'restore.requests':
    'Solicitudes',
  'restore.requestsDescription':
    'Cada solicitud y en que punto esta. Una rechazada se conserva, porque es justo por la que se pregunta despues.',
  'restore.name':
    'Archivo',
  'restore.copied':
    'Copiado',
  'restore.size':
    'Tamano',
  'restore.state':
    'Estado',
  'restore.present':
    'Sigue aqui',
  'restore.deleted':
    'Eliminado',
  'restore.verified':
    'Copia verificada',
  'restore.unverified':
    'Copiado, sin verificar',
  'restore.ask':
    'Solicitar restauracion',
  'restore.asking':
    'Solicitando...',
  'restore.cancel':
    'Cancelar',
  'restore.reason':
    'Por que se necesita este archivo',
  'restore.reasonHint':
    'Quien apruebe la solicitud lo leera. Se conserva junto a ella.',
  'restore.overwrite':
    'Sustituir el archivo existente',
  'restore.overwriteHint':
    'Sin esta opcion el archivo vuelve como copia nueva. No se sustituye nada.',
  'restore.overwriteWarning':
    'El archivo que hay ahora sera sustituido por la copia de seguridad. Quien apruebe debe confirmarlo por separado.',
  'restore.askNewCopy':
    'Solicitar una copia nueva',
  'restore.askOverwrite':
    'Solicitar sustituir el archivo',
  'restore.emptyBackups':
    'Ningun archivo tiene copia de seguridad todavia. Las copias se ejecutan cada noche una vez configurado un destino.',
  'restore.emptyRequests':
    'Nadie ha solicitado una restauracion.',
  'restore.pending':
    'Ya solicitado',
  'restore.approve':
    'Aprobar',
  'restore.approveOverwrite':
    'Aprobar la sustitucion del archivo',
  'restore.refuse':
    'Rechazar',
  'restore.who':
    'Solicitado por',
  'restore.yours':
    'Usted lo solicito, asi que lo aprueba otra persona.',
  'restore.refresh':
    'Actualizar',
  'restore.error.forbidden':
    'No tiene permiso para restaurar archivos.',
  'restore.error.unavailable':
    'Las restauraciones no estan disponibles en este momento. Intentelo en breve.',
  'imports.title':
    'Importación de datos',
  'imports.description':
    'Traiga registros desde una hoja de cálculo. Suba un archivo, indique a qué corresponde cada columna y vea exactamente qué pasaría antes de que se escriba nada.',
  'imports.startTitle':
    'Iniciar una importación',
  'imports.startDescription':
    'Elija qué va a importar y cómo tratar los duplicados, y después seleccione el archivo.',
  'imports.target':
    'Qué se importa',
  'imports.operation':
    'Registros existentes',
  'imports.operationHint':
    'Qué debe ocurrir con una fila que coincide con un registro que ya tiene.',
  'imports.file':
    'Archivo',
  'imports.ceiling':
    'Hasta {rows} filas por ejecución. Formatos admitidos: {formats}.',
  'imports.mapTitle':
    'Emparejar las columnas',
  'imports.mapDescription':
    'Cada columna de su archivo va a un campo, o a ninguno. Las columnas cuyo encabezado coincidió exactamente ya están emparejadas.',
  'imports.mapColumn':
    'A qué campo va la columna «{column}»',
  'imports.column':
    'Columna',
  'imports.sample':
    'Primer valor',
  'imports.field':
    'Campo',
  'imports.ignore':
    'No importar',
  'imports.check':
    'Comprobar el archivo',
  'imports.checking':
    'Comprobando…',
  'imports.discard':
    'Descartar esta importación',
  'imports.tooManyRows':
    'Este archivo tiene más filas de las que admite una ejecución. Divídalo e importe las partes por separado.',
  'imports.replaced':
    'Algunos caracteres de este archivo no se pudieron leer y se sustituyeron. Revise la vista previa antes de continuar.',
  'imports.resultTitle':
    'Qué pasaría',
  'imports.summary':
    '{rows} filas leídas, {valid} listas para importar, {errors} problemas encontrados.',
  'imports.wroteNothing':
    'Todavía no se ha escrito nada. Confirme abajo cuando las cifras sean correctas.',
  'imports.confirm':
    'Importar estos registros',
  'imports.confirmHint':
    'Esto escribe los registros en {product}. No se puede deshacer desde esta página.',
  'imports.committing':
    'Importando…',
  'imports.notCommittable':
    'Esta importación se puede comprobar pero no escribir. Todavía no hay nada en este producto que acepte estos registros.',
  'imports.wrote':
    '{created} de {total} registros se han importado.',
  'imports.downloadReport':
    'Descargar todos los problemas',
  'imports.showReport':
    'Mostrar los problemas',
  'imports.reportCut':
    'Solo se enumeran los primeros problemas. Corríjalos y vuelva a comprobar el archivo.',
  'imports.row':
    'Fila',
  'imports.problem':
    'Problema',
  'imports.value':
    'Valor',
  'imports.open':
    'Abrir',
  'imports.openRun':
    'Abrir la importación {target} y su informe',
  'imports.historyTitle':
    'Importaciones recientes',
  'imports.noRuns':
    'Todavía no se ha importado nada.',
  'imports.noTargets':
    'Este producto todavía no admite ninguna importación.',
  'imports.state':
    'Estado',
  'imports.rows':
    'Filas',
  'imports.started':
    'Iniciada',
  'imports.op.create':
    'Añadir cada fila como registro nuevo',
  'imports.op.update':
    'Actualizar solo los registros que ya existen',
  'imports.op.upsert':
    'Actualizar donde coincida y añadir donde no',
  'imports.op.skipDuplicate':
    'Añadir registros nuevos y dejar las coincidencias como están',
  'imports.state.created':
    'Pendiente de emparejar',
  'imports.state.mapped':
    'Columnas emparejadas, sin comprobar',
  'imports.state.validating':
    'Comprobando el archivo…',
  'imports.state.validated':
    'Comprobado. No se escribió nada.',
  'imports.state.validationFailed':
    'Se encontraron problemas. No se escribió nada.',
  'imports.state.commitRequested':
    'Pendiente de importar',
  'imports.state.committing':
    'Importando…',
  'imports.state.committed':
    'Importado',
  'imports.state.failed':
    'Esta importación no se pudo terminar',
  'imports.state.cancelled':
    'Cancelada',
  'imports.problem.required':
    'Este campo es necesario y la celda está vacía',
  'imports.problem.tooLong':
    'Este valor es más largo de lo que admite el campo',
  'imports.problem.notAnOption':
    'Este no es uno de los valores que acepta el campo',
  'imports.problem.integer':
    'Aquí se espera un número entero',
  'imports.problem.decimal':
    'Aquí se espera un número',
  'imports.problem.boolean':
    'Aquí se espera sí o no',
  'imports.problem.date':
    'Aquí se espera una fecha con el formato AAAA-MM-DD',
  'imports.problem.email':
    'Esto no parece una dirección de correo electrónico',
  'imports.problem.extraCells':
    'Esta fila tiene más celdas que columnas tiene el archivo',
  'imports.problem.ambiguousDecimal':
    'Esto se puede leer de dos maneras que difieren en mil veces. Escríbalo sin separador de millares.',
  'imports.problem.duplicateInFile':
    'Otra fila de este mismo archivo ya tiene este valor',
  'imports.template.download':
    'Descargar plantilla',
  'imports.template.hint':
    'Empiece con una plantilla que tenga los encabezados de columna correctos. Rellénela, guárdela y súbala aquí.',
  'imports.template.xlsx':
    'Excel (.xlsx)',
  'imports.template.csv':
    'CSV (.csv)',
  'imports.template.formatRefused':
    'No hay plantilla disponible en ese formato para esta importación.',
  'imports.limits':
    'Archivos de hasta {size}. Hasta {rows} filas por ejecución. Formatos aceptados: {formats}.',
  'imports.chosenFile':
    '{name} ({size})',
  'imports.sheet':
    'Leído de la hoja «{sheet}».',
  'imports.template.compatible':
    'Todas las columnas coinciden con esta importación. No hay nada que asignar a mano.',
  'imports.template.unknownColumns':
    'Estas columnas no forman parte de esta importación y no se importarán a menos que las asigne: {columns}.',
  'imports.template.incompatible':
    'Estos campos obligatorios no tienen columna correspondiente: {fields}. Asígnelos abajo o descargue una plantilla nueva.',
  'imports.template.stale':
    'Este archivo se creó a partir de una plantilla anterior (versión {found}; la actual es {current}). Revise las columnas antes de continuar.',
  'imports.preview.total':
    'Filas',
  'imports.preview.valid':
    'Listas para importar',
  'imports.preview.invalid':
    'Con problemas',
  'imports.preview.duplicate':
    'Duplicadas en el archivo',
  'imports.preview.create':
    'Se añadirían',
  'imports.preview.update':
    'Se actualizarían',
  'imports.preview.skip':
    'Se dejarían igual',
  'imports.preview.unknown':
    'Si una fila añade o actualiza un registro no se sabe hasta que se ejecuta la importación: esta importación no puede consultar registros de antemano.',
  'imports.result.title':
    'Importación completada',
  'imports.result.total':
    'Total',
  'imports.result.created':
    'Creados',
  'imports.result.updated':
    'Actualizados',
  'imports.result.skipped':
    'Omitidos',
  'imports.result.failed':
    'Fallidos',
  'imports.consequence':
    'Consecuencia',
  'imports.consequence.invalid':
    'La fila no se importará',
  'imports.problem.alreadyExists':
    'Ya existe un registro con este valor, y esta importación solo añade registros nuevos',
  'imports.format':
    'Formato',
  'imports.error.forbidden':
    'No tiene permiso para importar registros.',
  'imports.error.unavailable':
    'Las importaciones no están disponibles en este momento. Vuelva a intentarlo en breve.',
  'audit.title':
    'Auditoría',
  'audit.description':
    'Qué ha ocurrido en su organización: quién hizo qué, sobre qué registro y cómo terminó. Los registros se conservan el tiempo que exige su tipo y no más.',
  'audit.filters':
    'Filtros',
  'audit.action':
    'Acción',
  'audit.actor':
    'Persona',
  'audit.outcome':
    'Resultado',
  'audit.classification':
    'Tipo',
  'audit.any':
    'Cualquiera',
  'audit.apply':
    'Buscar',
  'audit.clear':
    'Limpiar',
  'audit.searching':
    'Buscando…',
  'audit.empty':
    'Aún no se ha registrado nada.',
  'audit.emptyFiltered':
    'No hay nada que coincida con esos filtros.',
  'audit.more':
    'Mostrar más',
  'audit.when':
    'Cuándo',
  'audit.what':
    'Acción',
  'audit.who':
    'Persona',
  'audit.target':
    'Registro',
  'audit.result':
    'Resultado',
  'audit.kind':
    'Tipo',
  'audit.details':
    'Detalles',
  'audit.exportTitle':
    'Exportar',
  'audit.exportDescription':
    'Obtenga una copia de los registros que coinciden con sus filtros. El archivo se prepara en segundo plano y permanece disponible durante siete días.',
  'audit.exportFormat':
    'Formato',
  'audit.exportStart':
    'Iniciar exportación',
  'audit.exportPending':
    'Actualizar',
  'audit.exportDownload':
    'Descargar',
  'audit.exportEmpty':
    'Aún no hay exportaciones.',
  'audit.exportRows.one':
    '{rows} registro',
  'audit.exportRows.other':
    '{rows} registros',
  'audit.restricted':
    'Algunos tipos de registro solo pueden leerlos propietarios o administradores.',
  'audit.error.forbidden':
    'No tiene permiso para leer el historial de auditoría.',
  'audit.error.unavailable':
    'El historial de auditoría no se pudo leer en este momento.',
  'settings.values.title': 'Ajustes de la organización',
  'settings.values.intro': 'Se aplican a todas las personas de {product}. Algunas pueden cambiarse individualmente.',
  'settings.values.save': 'Guardar',
  'settings.values.saving': 'Guardando',
  'settings.values.modified': 'Cambiado aquí',
  'settings.values.inherited': 'Valor de la plataforma',
  'settings.values.reset': 'Restablecer',
  'settings.values.resetTo': 'Vuelve a {value}',
  'settings.values.listHint': 'Separar con comas',
  'settings.values.on': 'Sí',
  'settings.values.off': 'No',
  'settings.values.saved': 'Guardado.',
  'settings.values.error': 'No se ha podido guardar. Revise los valores e inténtelo de nuevo.',
  'settings.values.forbidden': 'Solo un administrador puede cambiar los ajustes de la organización.',
  'settings.values.unavailable': 'Los ajustes no se pueden cargar en este momento.',
  'preferences.title': 'Mis preferencias',
  'preferences.intro': 'Se aplican a usted, en todos los dispositivos donde inicie sesión. Lo que no configure sigue a su organización.',
  'preferences.modified': 'Suyo',
  'preferences.inherited': 'De su organización',
  'preferences.resetTo': 'Vuelve a {value}',
  'preferences.saved': 'Guardado.',
  'preferences.error': 'No se ha podido guardar. Revise los valores e inténtelo de nuevo.',
  // The settings catalogue, rendered by the organisation's settings page
  // and by My preferences. Looked up from each definition's `label_key`, so
  // these keys are named by `settings_catalogue/standard.py` rather than by
  // any component -- see the exemption in `product-i18n.test.ts`.
  'settings.def.general.timezone.label': 'Zona horaria',
  'settings.def.general.timezone.description': 'La zona horaria en la que se muestran las fechas y horas.',
  'settings.def.general.language.label': 'Idioma',
  'settings.def.general.language.description': 'El idioma en el que se muestra este producto. Automático sigue al navegador.',
  'settings.def.general.dateFormat.label': 'Formato de fecha',
  'settings.def.general.dateFormat.description': 'Cómo se escriben las fechas.',
  'settings.def.general.timeFormat.label': 'Formato de hora',
  'settings.def.general.timeFormat.description': 'Si las horas se muestran en formato de 12 o 24 horas.',
  'settings.def.general.currency.label': 'Moneda',
  'settings.def.general.currency.description': 'La moneda en la que se muestran los importes para toda la organización.',
  'settings.def.general.firstDayOfWeek.label': 'Primer día de la semana',
  'settings.def.general.firstDayOfWeek.description': 'El día con el que empieza la semana.',
  'settings.def.ui.theme.label': 'Tema',
  'settings.def.ui.theme.description': 'Claro, oscuro o el que tenga configurado este dispositivo.',
  'settings.def.ui.density.label': 'Densidad de la interfaz',
  'settings.def.ui.density.description': 'Cuánto espacio deja la interfaz alrededor de los elementos.',
  'settings.def.ui.sidebarCollapsed.label': 'Empezar con la barra lateral contraída',
  'settings.def.ui.sidebarCollapsed.description': 'Abrir cada página con la navegación estrecha.',
  'settings.def.ui.defaultLandingPage.label': 'Página de inicio',
  'settings.def.ui.defaultLandingPage.description': 'A dónde lleva el inicio de sesión.',
  'settings.def.grid.pageSize.label': 'Filas por página',
  'settings.def.grid.pageSize.description': 'Cuántas filas muestra una tabla a la vez.',
  'settings.def.grid.pageSizeOptions.label': 'Opciones de filas por página',
  'settings.def.grid.pageSizeOptions.description': 'Los tamaños entre los que se puede elegir en una tabla.',
  'settings.def.grid.paginationEnabled.label': 'Paginar tablas largas',
  'settings.def.grid.paginationEnabled.description': 'Dividir las tablas largas en páginas en lugar de una lista larga.',
  'settings.def.grid.stickyHeader.label': 'Mantener visibles los encabezados',
  'settings.def.grid.stickyHeader.description': 'Los encabezados se quedan fijos mientras las filas se desplazan.',
  'settings.def.grid.rowDensity.label': 'Altura de fila',
  'settings.def.grid.rowDensity.description': 'Qué altura tienen las filas de una tabla.',
  'settings.def.grid.allowColumnResize.label': 'Columnas redimensionables',
  'settings.def.grid.allowColumnResize.description':
    'Permitir arrastrar el borde de una columna para hacerla más ancha o más estrecha.',
  'settings.def.grid.allowColumnReorder.label': 'Columnas movibles',
  'settings.def.grid.allowColumnReorder.description':
    'Permitir mover una columna a la izquierda o a la derecha en una tabla.',
  'settings.def.grid.rememberColumns.label': 'Recordar la disposición de columnas',
  'settings.def.grid.rememberColumns.description':
    'Conservar los anchos y el orden que alguien haya dispuesto, en este dispositivo.',
  // ── Notificaciones ────────────────────────────────────────────────────────
  'notifications.title': 'Notificaciones',
  'notifications.unread': '{count} sin leer',
  'notifications.empty': 'Nada pendiente',
  'notifications.emptyHint': 'Cuando algo necesite su atencion, aparecera aqui.',
  'notifications.markAllRead': 'Marcar todo como leido',
  'notifications.markRead': 'Marcar como leido',
  'notifications.dismiss': 'Descartar',
  'notifications.close': 'Cerrar notificaciones',
  'notifications.viewAll': 'Ver todas las notificaciones',
  'notifications.pageTitle': 'Notificaciones',
  'notifications.pageDescription': 'Todo lo que el producto le ha comunicado, lo mas reciente primero.',
  'notifications.hiddenTitle': 'Las notificaciones estan desactivadas',
  'notifications.hiddenBody': 'Ha desactivado las notificaciones en el producto. Puede volver a activarlas en sus preferencias.',
  'settings.def.notifications.inAppEnabled.label': 'Notificaciones en el producto',
  'settings.def.notifications.inAppEnabled.description': 'Mostrar notificaciones mientras esté conectado.',
  'settings.def.notifications.emailEnabled.label': 'Notificaciones por correo',
  'settings.def.notifications.emailEnabled.description':
    'Enviar también un correo cuando algo esté esperando por usted.',
  'settings.def.files.maxUploadSizeMb.label': 'Archivo más grande',
  'settings.def.files.maxUploadSizeMb.description': 'El archivo individual más grande que se puede subir aquí, en megabytes.',
  'settings.def.files.allowedExtensions.label': 'Tipos de archivo permitidos',
  'settings.def.files.allowedExtensions.description': 'Qué extensiones de archivo se pueden subir.',
  'settings.def.files.previewEnabled.label': 'Vista previa de archivos',
  'settings.def.files.previewEnabled.description': 'Mostrar una vista previa en lugar de solo el nombre.',
  'settings.def.reporting.defaultDateRange.label': 'Periodo predeterminado',
  'settings.def.reporting.defaultDateRange.description': 'El periodo con el que se abre un informe.',
  'settings.def.reporting.defaultExportFormat.label': 'Formato de exportación predeterminado',
  'settings.def.reporting.defaultExportFormat.description': 'El formato que ofrece primero una exportación.',
  'settings.def.accessibility.highContrast.label': 'Mayor contraste',
  'settings.def.accessibility.highContrast.description': 'Más contraste entre el texto y el fondo.',
  // The seven groups the two pages lay their settings out in.
  'settings.category.general': 'General',
  'settings.category.appearance': 'Apariencia',
  'settings.category.grid': 'Tablas',
  'settings.category.notifications': 'Notificaciones',
  'settings.category.files': 'Archivos',
  'settings.category.reporting': 'Informes',
  'settings.category.accessibility': 'Accesibilidad',
  // Option labels, shared by value: `compact` means the same wherever it
  // appears, and two entries for one word is two a translator must keep level.
  'settings.option.auto': 'Automático',
  'settings.option.system': 'Según el dispositivo',
  'settings.option.light': 'Claro',
  'settings.option.dark': 'Oscuro',
  'settings.option.comfortable': 'Cómoda',
  'settings.option.compact': 'Compacta',
  'settings.option.iso': '2026-09-19',
  'settings.option.dmy': '19/09/2026',
  'settings.option.mdy': '09/19/2026',
  'settings.option.long': '19 de septiembre de 2026',
  'settings.option.monday': 'Lunes',
  'settings.option.sunday': 'Domingo',
  'settings.option.saturday': 'Sábado',
  'settings.option.never': 'Nunca',
  'settings.option.daily': 'A diario',
  'settings.option.weekly': 'Semanalmente',
  'settings.option.last7': 'Últimos 7 días',
  'settings.option.last30': 'Últimos 30 días',
  'settings.option.last90': 'Últimos 90 días',
  'settings.option.lastYear': 'Último año',
  'settings.option.12h': '12 horas',
  'settings.option.24h': '24 horas',
  'settings.option.csv': 'CSV',
  'settings.option.xlsx': 'Excel',
  'settings.option.pdf': 'PDF',
  // La paginación de la tabla compartida.
  'grid.pagination': 'Paginación',
  'grid.rowsPerPage': 'Filas por página',
  'grid.previous': 'Anterior',
  'grid.next': 'Siguiente',
  'grid.showing': 'Mostrando {from} a {to} de {total}',
  'grid.page': 'Página {page} de {pages}',
  'grid.moveColumnLeft': 'Mover {column} a la izquierda',
  'grid.moveColumnRight': 'Mover {column} a la derecha',
  'errors.tokenInvalid': 'Su sesión ha caducado. Inicie sesión de nuevo.',
  'errors.tenantInactive': 'Su organización no está activa en este producto.',
  'errors.roleRequired': 'Solo un propietario o administrador de su organización puede hacer eso.',
  'errors.permissionMissing': 'Su rol no incluye eso.',
  'errors.entitlementMissing': 'Su plan no incluye esto.',
  'errors.storageLimitExceeded': 'Esta subida superaría el almacenamiento incluido en su plan.',
  'errors.fileNotFound': 'Ese archivo ya no existe.',
  'errors.uploadNotArrived':
    'El archivo no llegó al almacenamiento como se esperaba. Intente subirlo de nuevo.',
  'errors.uploadSizeMismatch':
    'El archivo subido no tiene el tamaño anunciado. Intente subirlo de nuevo.',
  'errors.backupNotFound':
    'No existe ninguna copia de seguridad de este archivo desde la que restaurarlo.',
  'errors.restoreNotFound':
    'No existe esa solicitud de restauración.',
  'errors.restoreNotTransitionable':
    'Esta solicitud de restauración ya se ha decidido.',
  'errors.restoreAlreadyRequested':
    'Ya hay una restauración de este archivo esperando una decisión.',
  'errors.restoreOverwriteUnconfirmed':
    'Esta solicitud sustituye el archivo existente. Apruébela indicándolo, o solicite una copia nueva en su lugar.',
  'errors.importTargetNotFound':
    'Este producto no admite una importación de ese tipo.',
  'errors.importRunNotFound':
    'No se encuentra esa importación.',
  'errors.importMappingRefused':
    'Las columnas no se pueden emparejar tal como están. El mensaje indica cuál.',
  'errors.importFileUnreadable':
    'No se pudo leer este archivo. Compruebe que es un CSV guardado con una fila de encabezados.',
  'errors.importTooManyRows':
    'Este archivo tiene más filas de las que admite una importación. Divídalo e importe las partes por separado.',
  'errors.importOperationRefused':
    'Eso no es algo que esta importación pueda hacer.',
  'errors.importNotTransitionable':
    'Esta importación ha avanzado y eso ya no es posible.',
  'errors.importQueueUnavailable':
    'El trabajo en segundo plano no está configurado, así que este archivo no se puede comprobar. Tiene que configurarlo una persona administradora.',
  'errors.importNotCommittable':
    'Esta importación se puede comprobar pero no escribir. Todavía no hay nada en este producto que acepte estos registros.',
  'errors.importFileTooLarge':
    'Este archivo es más grande de lo que lee una importación. Divídalo e importe las partes por separado.',
  'errors.importFormatRefused':
    'Este tipo de archivo no se puede importar aquí. Descargue una plantilla para ver los formatos aceptados.',
  'errors.uploadRefusedByPolicy':
    'Este archivo no se admite. Compruebe su tamaño y su tipo frente a la configuración de su organización.',
  'errors.fileUnderHold':
    'Este archivo no se puede eliminar: una retención legal lo conserva. Podrá eliminarse cuando se levante la retención.',
  'errors.fileQuarantined':
    'Este archivo está retenido porque un análisis de seguridad no lo consideró limpio. Consulte a un administrador si lo necesita.',
  'errors.notificationNotFound':
    'Esa notificacion ya no esta. Es posible que ya se haya leido o descartado.',
  'errors.settingNotFound':
    'Ese ajuste no existe. Vuelva a cargar la página para ver la lista actual.',
  'errors.settingValueInvalid':
    'Ese valor no se admite en este ajuste. El intervalo permitido se muestra al lado.',
  'errors.settingScopeRefused':
    'Este ajuste se decide para toda la organización y no puede cambiarse aquí.',
  'errors.holdNotFound':
    'Esa retención legal no existe.',
  'errors.holdNotTransitionable':
    'Esa retención legal ya se ha decidido; recargue la lista para ver su estado actual.',
  'errors.holdInvalidWindow':
    'Una retención legal no puede terminar antes de empezar.',
  'errors.auditEventNotFound':
    'Ese evento de auditoría no existe.',
  'errors.storageUnavailable': 'El almacenamiento de archivos no está disponible en este momento.',
  'errors.reportNotFound': 'Ese informe no existe.',
  'errors.scheduleNotFound': 'Esa programación ya no existe.',
  'errors.exportNotFound': 'Esa exportación ya no existe.',
  'errors.exportFormatUnknown': 'Ese formato de exportación no se reconoce.',
  'errors.exportFormatUnsupported': 'Este informe no puede exportarse en ese formato.',
  'errors.filterInvalid': 'Uno de los filtros no es válido para este informe.',
  'errors.recipientInvalid': 'Uno de los destinatarios no es una dirección de correo.',
  'errors.periodNotAFilter': 'El periodo de un informe programado lo decide su cadencia.',
  'errors.reportFailed': 'No se pudo generar el informe. Inténtelo más tarde.',
  'errors.toolDenied': 'Su rol no permite eso en el asistente.',

  /* ----------------------------------------------------------- governance */
  'governance.title': 'Gobernanza',
  'governance.description':
    'Retenciones legales y cuánto tiempo conserva esta organización lo que almacena. Una retención impide borrar todo lo que cubre, incluidas las purgas nocturnas.',
  'governance.holds': 'Retenciones legales',
  'governance.holdsDescription':
    'Cada retención y en qué punto está. Una levantada se conserva, porque es por la que alguien pregunta más adelante.',
  'governance.reason': 'Por qué hace falta esta retención',
  'governance.reasonHint':
    'Indique el asunto. Lo lee quien la aprueba y cualquiera que revise la retención después.',
  'governance.scope': 'Qué cubre',
  'governance.scopeTenant': 'Todo lo de esta organización',
  'governance.scopeFiles': 'Solo archivos',
  'governance.scopeAudit': 'Solo registros de auditoría',
  'governance.endsAt': 'Termina el (opcional)',
  'governance.endsAtHint':
    'Déjelo vacío para una retención sin fin. Una retención abierta conserva todo lo que cubre hasta que alguien la levante.',
  'governance.ask': 'Solicitar una retención',
  'governance.asking': 'Solicitando…',
  'governance.status': 'Estado',
  'governance.inForce': 'En vigor ahora',
  'governance.notInForce': 'No retiene nada',
  'governance.who': 'Solicitada por',
  'governance.yours': 'Esta debe decidirla alguien que no sea usted.',
  'governance.approve': 'Aprobar',
  'governance.release': 'Levantar esta retención',
  'governance.releaseWarning':
    'Lo que cubre podrá volver a borrarse desde la próxima purga nocturna.',
  'governance.emptyHolds': 'No se ha solicitado ninguna retención.',
  'governance.refresh': 'Actualizar',
  'governance.retention': 'Cuánto tiempo se conserva',
  'governance.retentionDescription':
    'Días, por tipo. Deje una casilla vacía para usar el valor por defecto de la plataforma.',
  'governance.retentionFloorHint':
    'Puede pedir más que el valor por defecto, nunca menos: un número menor se acepta y se aplica el mayor de los dos. El máximo es 3650 días.',
  'governance.days': 'días',
  'governance.save': 'Guardar',
  'governance.saving': 'Guardando…',
  'governance.saved': 'Guardado.',
  'governance.kind.auditActivity': 'Registros de actividad diaria',
  'governance.kind.audit': 'Registros de auditoría',
  'governance.kind.auditSecurity': 'Registros de seguridad',
  'governance.kind.storageStandard': 'Archivos ordinarios',
  'governance.kind.storageSensitive': 'Archivos sensibles',
  'governance.kind.storageRestricted': 'Archivos restringidos',
  'governance.error.forbidden':
    'No tiene permiso para hacer eso. Poner o levantar una retención requiere el permiso de retención, y aprobar o levantar requiere una propietaria o administradora que no la haya solicitado.',
  'governance.error.unavailable':
    'No se ha podido leer la gobernanza en este momento. No se ha cambiado nada.',
}
