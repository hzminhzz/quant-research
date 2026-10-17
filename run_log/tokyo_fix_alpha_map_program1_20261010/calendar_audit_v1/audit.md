# Tokyo bank calendar audit

This audit reads no prices. It does not read September 2026 or later price outcomes. The study instrument is USDJPY. The economic premise is that scheduled importer payments can create dollar demand before the Tokyo fix. Calendar labels can test this premise. They do not prove that importer orders occurred.

The [Bank of Japan holiday schedule](https://www.boj.or.jp/en/about/outline/holi.htm) supplies the bank closure rule: weekends, national and substitute holidays, and December 31 through January 3. The [Cabinet Office holiday page](https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html) supplies the statutory rules and Olympic exceptions. Its [historic CSV](https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv) supplies the exact national and substitute holiday dates. All three pages were fetched with TinyFish on 2026-10-10. Adjacent JSON files preserve the full tool responses. TinyFish batch tools were not available in this agent's tool catalog. Each fetch used one URL.

## Verified calendar evidence

- The in-scope CSV contains 120 national and substitute holiday dates from 2020-01-01 through 2026-08-31. Year counts are 18, 17, 16, 17, 21, 19, and 12, respectively.
- Applying the BOJ rule yields 1,627 bank business dates within 2,435 calendar dates.
- The nominal Gotobi dates are 5, 10, 15, 20, 25, and 30 when that date exists. February has no day 30. Month-end remains a separate label.
- There are 473 nominal events and 152 rolled nominal events. They map to 470 distinct in-scope event dates.
- Two event dates combine nominal labels: 2021-04-30 combines April 30 and May 5; 2024-12-30 combines December 30 and January 5, 2025. Keep one price observation per event date. The January 5, 2020 nominal event rolls to December 30, 2019, outside this sample.
- There are 80 last bank business dates of the month and 26 last bank business dates of the quarter. Friday is recorded separately.
- Olympic holiday assertions pass: 2020 July 23/24 and August 10; 2021 July 22/23 and August 8/9. August 11 is not a public holiday in either year.

## Assumptions and limitations

Rolling a closed nominal date to the previous Tokyo bank business date is a frozen research assumption. Neither official source states that all corporate foreign exchange flows obey that rule. Settlement rules can depend on the contract, the firm's payment practice, and foreign currency banking calendars. The study must call this a calendar proxy.

The negative-control date label for days 2/7/12/17/22/27 identifies business dates without a Gotobi event. It is a research design choice. It is not a source claim that these dates have no settlement demand.

The fetched official CSV has readable ASCII dates but its Japanese holiday names show character encoding damage. Dates are parsed from the intact first column. Exact original CSV bytes were not downloaded, so the archived hash identifies the TinyFish response, not the upstream byte stream. BOJ HTML table captions conflict with their section headings; the section years agree with the Cabinet Office dates. The study uses the Cabinet Office CSV for exact dates and BOJ for closure rules.

These current official records do not archive the publication vintage available at each past decision. The calendar is suitable for an exploratory historical event classification. The 2021 Olympic holiday revision must have been announced before a strategy used it prospectively. This audit does not verify every historical announcement timestamp. It does not support an unseen performance claim.

This audit does not assume that FX prices are absent on Tokyo holidays. It labels Tokyo bank status independently from provider completeness. It does not forward-fill execution prices or exclude a day based on its return.

## Skills and invariant checks

The complete local skills read were `.agents/skills/ml4t-calendar-ops/SKILL.md`, `.agents/skills/ml4t-validate-data/SKILL.md`, `.agents/skills/ml4t-point-in-time/SKILL.md`, and their applicable dependencies `ml4t-fetch-data` and `ml4t-lookahead-bias`.

Calendar operations require explicit market closure rules, explicit timezones, and business-day offsets. The builder uses BOJ rules with `Asia/Tokyo` dates, and asserts that every rolled date is a business date no later than its nominal date. The skill suggests forward-filling cross-market feature values; the mission prohibits this for execution prices. This calendar does not fill prices.

Data validation requires exact schema, duplicate checks, and coverage checks. `holidays.json` uses ISO dates, and `build_calendar.py` asserts holiday counts, complete date coverage, Olympic exceptions, and selected Golden Week and year-end cases. `calendar_dates.csv` has one row per calendar date. `nominal_gotobi_events.json` preserves the separate nominal identity when event dates collide.

Point-in-time and lookahead skills require availability time separation and past-only inputs. This builder reads only official calendar facts and frozen classification rules. It reads no prices. Missing historical announcement vintages are disclosed above; no past outcome can alter the calendar.

Run `python run_log/tokyo_fix_alpha_map_program1_20261010/calendar_audit_v1/build_calendar.py` to reproduce the registry and assertions. `verification.json` records counts, passed assertions, and artifact hashes. Research conclusions depend on independent price coverage and statistical tests performed by the main mission.
