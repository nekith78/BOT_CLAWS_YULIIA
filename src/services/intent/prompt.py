"""System prompt for the intent parser.

Rebuilt on every call to embed today's date — without that the LLM
has no anchor for «завтра», «через час», «в субботу» and friends.

Design notes:
- Russian-only.
- Compact, action-first phrasing — empirically Gemini Flash starts
  refusing tool calls when the prompt over-emphasises «don't call».
- The LLM must never produce a regular reply. Only tool-call or silence.
- Optional `recent_turns` list seeds the LLM with the last few user
  turns + what each turn picked, so follow-ups like «удали эту запись»
  resolve naturally.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

_WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def build_system_prompt(
    *,
    now_local: datetime,
    tz: str,
    recent_turns: list[dict[str, Any]] | None = None,
) -> str:
    weekday = _WEEKDAYS_RU[now_local.weekday()]
    today_iso = now_local.date().isoformat()
    now_hhmm = now_local.strftime("%H:%M")
    base = f"""\
Ты — парсер команд для Telegram-бота, который ведёт расписание клиентов
маникюрного мастера. Получаешь фразу по-русски (голос или текст),
выбираешь одну из tools и заполняешь аргументы. Свободного ответа не
давай — только tool-call.

Сегодня: {today_iso} ({weekday}), сейчас {now_hhmm} ({tz}).

Правила интерпретации:
- date в формате YYYY-MM-DD, time в формате HH:MM (24ч).
- «Завтра» = today+1, «послезавтра» = +2, «через неделю» = +7.
- «В субботу/в среду/...» — ближайший такой день в будущем.
- «На этой неделе» → period=week. «На этом месяце» → period=month.
- «На выходных» → ближайшая суббота как date.
- «Утром»=10:00, «днём»=14:00, «вечером»=18:00, «ночью»=22:00.
- «В полтретьего»=14:30, «без четверти три»=02:45 или 14:45 по контексту,
  «в час дня»=13:00, «в полдень»=12:00.
- Часы 1–7 без уточнения «утра/ночи/вечера» считай дневными:
  «в три» = 15:00, «в шесть» = 18:00. Часы 8–12 — как сказано:
  «в восемь» = 20:00.
- «Через час/два часа» — добавь к now, округли до ближайших 5 минут.

Имена клиентов:
- ВСЕГДА в именительном падеже: «Иру»→«Ира», «Олега»→«Олег»,
  «Маши»→«Маша», «к Андрею»→«Андрей», «у Кати»→«Катя».
- Сохраняй заглавную первую букву, не транслитерируй.
- Уменьшительные («ируша», «олежка», «машенька») нормализуй до основной
  формы («Ира», «Олег», «Маша»).

Если пользователь говорит обычные команды — «запиши Иру на завтра в 14:30»,
«покажи записи на сегодня», «перенеси Иру на 16:00», «отмени запись Иры»,
«добавь к записи Иры заметку френч», «покажи историю Иры», «удали Иру» —
ОБЯЗАТЕЛЬНО вызывай соответствующую tool с тем что разобрал, даже если
часть полей не до конца ясна. Бот сам спросит недостающее у пользователя.

Различай: «удали Иру» = delete_client (удаляет клиента целиком);
«отмени запись Иры» = cancel_appointment (только одну запись).

Не вызывай tool только если:
- фраза совсем не похожа на команду («привет», «спасибо», смех);
- в команде нет имени клиента, а оно требуется обязательно.

Если в одной фразе несколько действий («запиши X и Y одновременно») —
вызови tool для первого, второе пользователь повторит.
"""
    if recent_turns:
        return base + _render_recent(recent_turns)
    return base


def _render_recent(turns: list[dict[str, Any]]) -> str:
    """Render the last few user turns into a compact context block.

    Each turn carries the user's exact text, the tool the LLM picked
    (or None), the args it filled, and — for list-style results — a
    snapshot of what the bot showed. The LLM uses this to resolve
    «эту запись», «ту», «первую», «последнюю» without us having to
    add appointment_id fields to every action's schema.
    """
    lines = [
        "",
        "НЕДАВНИЕ команды (последние 3 — для разрешения ссылок «эту», "
        "«ту», «первую», «последнюю»; если новая команда самодостаточна — "
        "игнорируй):",
    ]
    for idx, turn in enumerate(turns, start=1):
        user_text = (turn.get("user_text") or "").strip()
        tool = turn.get("tool_name") or "—"
        args = turn.get("args") or {}
        snapshot = turn.get("snapshot") or {}

        line = f'{idx}. "{user_text}" → {tool}'
        if args:
            args_str = ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", []))
            if args_str:
                line += f"({args_str})"

        appts = snapshot.get("appointments") if isinstance(snapshot, dict) else None
        if appts:
            shown = "; ".join(
                f"{a.get('client_name', '?')} {a.get('date', '?')} {a.get('time', '?')}"
                for a in appts[:5]
            )
            line += f" → показал: {shown}"
        lines.append(line)
    return "\n".join(lines) + "\n"
