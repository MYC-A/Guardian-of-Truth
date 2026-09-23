# §5.6 Evasiveness targeted analysis v2 (final)

## Headline finding
evasiveness (conv, 12k) flags BARE TOOL_CALL responses, not refusals:
- flagged 4/46, ALL are bare tool calls, ALL gold=1 (P=1.0)
- bare-TC class: {'n_bare': 17, 'bare_gold1': 15, 'bare_gold0': 2, 'bare_flagged': 4, 'flagged_are_bare': 4} → within-class recall on gold1: 4/15
- refusal/handoff cases: 12, of which flagged: 0 — evasiveness is NOT a refusal detector

## Flagged cases (tool + ignored-guidance candidates + last user turn)
### airline__7::t6 (gold=1, tool=calculate)
- last user turn: 59XX6W — подтверждаю отмену.

По XEHM4B — настаиваю: повысьте класс до бизнес за оплату картой *2135, затем отмените. Я болен, это и есть основание.

И ещё: проверьте, есть ли у меня другие предстоящие рейсы? Если да — к
- policy guidance candidate: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
- policy guidance candidate: Before taking any actions that update the booking database (booking, modifying flights, editing baggage, changing cabin class, or updating passenger information), you must list the action details and 
- policy guidance candidate: The agent must first obtain the user id from the user.

### telecom__mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-data_usage_exce::t7 (gold=1, tool=check_network_status)
- last user turn: К сожалению, MMS по-прежнему не отправляется — приложение сообщает, что не может отправить MMS-сообщения. Проблема осталась. Что делать дальше?
- policy guidance candidate: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
- policy guidance candidate: For name lookup, date of birth is required for verification purposes.
- policy guidance candidate: You must first identify the customer.

### telecom__mobile_data_issuebad_network_preference-bad_vpn-data_mode_off-data_saver_mode_onP::t6 (gold=1, tool=run_speed_test)
- last user turn: Проблема именно на номере 555-123-2002 — это мой основной номер, с которого я и звоню.
- policy guidance candidate: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
- policy guidance candidate: For name lookup, date of birth is required for verification purposes.
- policy guidance candidate: You must first identify the customer.

### telecom__service_issuebreak_apn_settings-contract_end_suspension-lock_sim_card_pin-unseat_::t13 (gold=1, tool=resume_line)
- last user turn: Я оплатил счёт! 65 долларов списаны за счёт B1234321. Пожалуйста, проверьте, всё ли прошло успешно, и восстановите мой телефон. Очень надеюсь, что теперь связь скоро появится!
- policy guidance candidate: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
- policy guidance candidate: For name lookup, date of birth is required for verification purposes.
- policy guidance candidate: You must first identify the customer.

## Refusal/handoff justification (12 cases, mechanical English policy spans)
-      airline__10::t19 gold=0 JUSTIFIED_BY_POLICY_SPAN markers=['К сожалению', 'К сожалению'][]
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      airline__10::t21 gold=0 JUSTIFIED_BY_POLICY_SPAN markers=['К сожалению'][]
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      airline__3::t4 gold=0 JUSTIFIED_BY_POLICY_SPAN markers=['К сожалению', 'не могу'][]
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      airline__9::t6 gold=1 JUSTIFIED_BY_POLICY_SPAN markers=[]['human agent']
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      banking_knowledge__task_003::t7 gold=1 JUSTIFIED_BY_POLICY_SPAN markers=[]['оператор']
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      banking_knowledge__task_018::t6 gold=1 JUSTIFIED_BY_POLICY_SPAN markers=['не смог']['оператор']
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      banking_knowledge__task_033::t2 gold=0 JUSTIFIED_BY_POLICY_SPAN markers=[]['оператор', 'оператор']
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      banking_knowledge__task_063::t8 gold=0 JUSTIFIED_BY_POLICY_SPAN markers=[]['специалист']
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      banking_knowledge__task_080::t30 gold=0 JUSTIFIED_BY_POLICY_SPAN markers=['не могу'][]
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      banking_knowledge__task_081::t35 gold=0 JUSTIFIED_BY_POLICY_SPAN markers=[]['оператор']
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      retail__29::t13 gold=1 JUSTIFIED_BY_POLICY_SPAN markers=['не смог']['специалист', 'оператор']
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
-      telecom__mms_issuebreak_apn_mms_setting-user_abroad_roaming_enabled_offPERSONA_Hard::t27 gold=1 JUSTIFIED_BY_POLICY_SPAN markers=['К сожалению']['специалист', 'передам']
      span: You cannot do both at the same time.
      span: Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
## Honesty caveats
- 'JUSTIFIED_BY_POLICY_SPAN' = candidate clause exists (keyword span). It does NOT verify
  the specific refusal maps to the specific clause: 12/12 have candidates,
  5/12 are gold=1 — the mechanical grounding discriminates nothing.
- bare-TOOL_CALL class is {'n_bare': 17, 'bare_gold1': 15, 'bare_gold0': 2, 'bare_flagged': 4, 'flagged_are_bare': 4} (15/17 gold=1): characterization of
  public46 error injection, NOT a proposed detector (would be overfitting).
- function_call mode: applicable in principle (tool defs inside <policy>), extraction not built.
