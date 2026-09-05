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
  'login.note':
    'El inicio de sesión usa la cuenta de su organización. No hay una contraseña separada de {product} que recordar ni restablecer.',

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

  'reports.title': 'Informes',
  'reports.notIncluded.title': 'No incluido en su plan',
  'reports.notIncluded.description':
    'Los informes avanzados forman parte de un plan superior. Su plan actual es <strong>{plan}</strong>.',
  'reports.notIncluded.notRecorded': 'no registrado',
  'reports.unresolved':
    'No se ha podido leer su plan desde la plataforma KORAS en este momento, así que puede que esto esté disponible para usted. El motivo está en el registro del servidor de esta instalación.',
  'reports.included':
    'Incluido en su plan. Construya aquí lo real: esta página existe para que la comprobación del plan lleve a algún sitio y para que el patrón sea visible antes de que alguien lo necesite.',

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
}
