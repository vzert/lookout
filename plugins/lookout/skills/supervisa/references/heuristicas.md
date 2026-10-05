# Heurísticas de "atascado" (Fase 6)

Lo decide lookout con scripts y contadores en archivos (`counters.json`, derivado siempre de `events.jsonl`).
El supervisor no lleva cuentas ni consulta en bucle. Regla de oro: **nunca declarar atascado con una sola fuente**.

## Señales, umbrales y acciones

| Señal | Fuentes | Umbral | Evento | Acción del supervisor |
|---|---|---|---|---|
| Mismo error repetido | `PostToolUseFailure` del ejecutor: herramienta + línea `Exit code N` + primera línea de salida, con rutas y números en blanco (firma) | 3 fallos con la misma firma desde que arrancó la sesión; tras una corrección, 1 (el texto de la corrección pide aplicarla y correr una vez el mismo comando: si el error vuelve, la corrección falló). También falla si el agente reporta que sigue igual sin volver a correrlo: el supervisor lo cita con `corrige --reporte` | `repite` (despierta; "te necesita") | `lookout corrige … --resumen` y mandar su texto tal cual. Máximo 2 correcciones por firma: cuando falla la 2.ª, `corrige` dice `PARA` → escalar al usuario, sin ping-pong |
| Sin progreso | hooks (último evento en turno y viejo) + proceso de Claude (`ps`: detenido o muerto) + herdr (no `working`, o ya no lo lista) + worktree (archivos o HEAD sin cambios) | `mirar` ≥ 5 min; `escalar` ≥ 20 min; hacen falta los hooks viejos **y** otra fuente que diga "no trabaja", y el worktree quieto | `sin_progreso` (despierta; `escalar` = "te necesita") | `mirar`: una lectura de pantalla. `escalar`: avisar al usuario. Nunca relanzar ni matar por cuenta propia |
| Vivo pero callado | herdr `working` **y** proceso vivo, sin eventos de hook (un build o una suite larga) | ≥ 60 min | `largo` (una vez) | Una lectura de pantalla. No es atasco |
| Límite del proveedor | `StopFailure` con `error` = `rate_limit` u `overloaded` | inmediato | `pausa` (no despierta) | Nada: no es falla de la tarea. No relanzar ni marcar fallido |
| Otro error de API | `StopFailure` con otro `error` (credenciales, facturación, modelo…) | inmediato | `unknown` ("te necesita") | Avisar al usuario |
| Espera su adversario o un shell de fondo | `Stop` con `background_tasks` | inmediato | `bg_wait` | No es atasco (H12) |
| Escritura en otro proyecto por Bash | rutas que el texto del comando escribe (`>`, `>>`, `tee`, destino de `cp`/`mv`, `rm`, `mkdir`, `touch`, `sed -i`, `git -C`, `--work-tree`, `--git-dir` o `cd` + subcomando que escribe, y la carpeta nueva de `git worktree add/move`) cruzadas con los candados vivos | inmediato | `crossrepo` con `via=bash` (en los dos proyectos) | Preguntar al agente si era intencional (puede ser un falso positivo) |

Umbrales por variable de entorno (segundos): `LOOKOUT_MIRAR_S` (300), `LOOKOUT_ESCALAR_S` (1200), `LOOKOUT_LARGO_S`
(3600). El waiter corre el chequeo cada `LOOKOUT_REVISA_CADA` (30) segundos, y solo hace trabajo mientras algún agente
lleve más de `LOOKOUT_MIRAR_S` sin eventos estando en turno.

Por qué el mtime del transcript no cuenta como progreso: durante un Bash largo en primer plano no cambia (spike de la
Fase 6). Por qué el proceso se mira con `ps`: un Claude detenido (`SIGSTOP`) pierde el primer plano de su terminal y herdr
deja de listarlo; un Claude muerto (`kill -9`) no manda `SessionEnd`.

## Vista por grupos (`lookout resumen`)

| Grupo | Último evento de estado del agente |
|---|---|
| Te necesita | `ask`, `blocked`, `negado`, `repite`, `unknown`, `sin_progreso` nivel `escalar` |
| Listo para revisar | `idle` con `[COMPLETION-REVIEW …]` en su último mensaje, o tarea `terminada` |
| Trabajando | `working`, `bg_wait`, `correccion`, `largo`, `sin_progreso` nivel `mirar` |
| En pausa (proveedor) | `pausa` |
| Idle | cualquier otro `idle` (también el que ya le reportó al supervisor: suele ser una pregunta o "espero tu respuesta", y el supervisor ya tiene ese mensaje), `start` |

`fallo`, `aprobado`, `crossrepo` y las notificaciones de herdr no cambian el grupo: tras un `repite`, los fallos que
siguen dejan al agente en "Te necesita" hasta que llegue una corrección o un turno nuevo.

Aviso de herdr (`herdr notification show`) **solo al entrar** en "Te necesita" o en "Listo", una vez por cambio de
grupo. Sin aviso por `ask` (lo contesta el supervisor, D5) ni por `blocked` / `negado` (ya avisó el evaluador de
permisos de la Fase 5).

## Puertos y bases de datos

`bin/ports.py` da a cada worktree un puerto propio de `LOOKOUT_PORT_BASE` (4100) en adelante: el que ya tiene, o el
más bajo que nadie tiene asignado y que se puede abrir en 127.0.0.1 en ese momento. Se guarda en `<estado>/ports.json`
(toda la máquina) y se libera con `lookout libera`. El agente lanzado lo recibe como `$PORT` en su entorno y escrito en
su tarea, con un sufijo (`<carpeta del worktree>`) para nombres de bases de datos o cachés propias.

## Límites conocidos

- **El contador solo ve las correcciones que pasan por `lookout corrige`.** Si el supervisor le escribe al agente por
  `SendMessage` sin pasar por el script, ese mensaje no cuenta como corrección (en la corrida 1 de la Fase 6 el
  supervisor le pidió investigar por su cuenta, sin `repite` nuevo: no era una corrección, pero el contador tampoco la
  habría visto). Por eso la skill pide `corrige` siempre como primer paso ante un `repite`.
- **El waiter espera el fin de la vuelta del chequeo antes de salir**, hasta 30 s más 30 s por agente registrado; si una
  vuelta tarda más, el supervisor igual despierta y `resumen` recalcula los grupos desde `events.jsonl`, pero el aviso de
  esa vuelta puede perderse.
- **El chequeo de "sin progreso" corre dentro del waiter.** Mientras no hay waiter vivo (el supervisor atiende un turno
  largo), no se revisa: el aviso llega cuando el supervisor relanza el waiter (el hook Stop de la Fase 4 lo pide). En la
  corrida 1 el `escalar` del control llegó ~75 s después del umbral por eso.
- **Un agente muerto sin `SessionEnd` sigue en el registro.** El chequeo lo revisa en cada vuelta (una línea en
  `revisa.log`), pero avisa una sola vez por nivel.
- `revisa.log` (carpeta del proyecto en el estado de lookout) guarda una línea por agente revisado: qué vio (herdr,
  proceso, segundos sin eventos) y qué decidió. Sirve para distinguir "no avisó" de "no revisó".
