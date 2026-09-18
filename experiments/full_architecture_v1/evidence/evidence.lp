
% ================= generic four-valued evidence core (v1) =================
% value tags: num(N) | str(S) | bool(B);  truth: true false both unk

% value-domain grounding (facts with free variables are unsafe in ASP)
valsrc(V) :- sval(_, V).
valsrc(V) :- q_state(_, _, _, V, _).
valsrc(V) :- q_state_hist(_, _, _, V, _).
valsrc(V) :- q_cmp(_, _, _, _, V, _).
vmatch(V, V) :- valsrc(V).
vtype(num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
vtype(str(X), str(Y)) :- valsrc(str(X)), valsrc(str(Y)).
vtype(bool(X), bool(Y)) :- valsrc(bool(X)), valsrc(bool(Y)).

% ---- entity matching (wildcard * matches every mentioned entity)
ent(E) :- attempt_fact(_, _, E, _, _).
ent(E) :- completed_fact(_, _, E, _, _).
ent(E) :- failed_fact(_, _, E, _, _).
ent(E) :- state_fact(_, _, E, _, _).
ent(E) :- effect_fact(_, _, E, _, _, _).
entmatch(E, E) :- ent(E).
entmatch("*", E) :- ent(E).

% ---- mutation positions (attempted actions; observations are pure reads)
% attempted/completed/failed calls are potential mutations, scoped to
% the entity they touch (S2: "any attempted mutation OF THE ENTITY";
% full-architecture fix: the bake-off template was entity-UNscoped,
% invalidating state on any later attempt anywhere — a documented
% conservatism delta measured by ev31_noise_10k in the evidence benchmark)
mut(I, E) :- attempt_fact(_, _, E, _, I).
mut(I, E) :- completed_fact(_, _, E, _, I).
mut(I, E) :- failed_fact(_, _, E, _, I).

% ---- trusted state rows (observations + effects, with values)
row(F, E, P, V, I) :- state_fact(F, _, E, P, I), sval(F, V).
row(F, E, P, V, I) :- effect_fact(F, _, E, P, I, _), sval(F, V).

% ============================ query evaluation =============================

% ---- generic four-valued completion for evidence-based queries
tval(Q, true) :- q_attempted(Q, _, _, _, _), sup(Q, _), not ref(Q).
tval(Q, false) :- q_attempted(Q, _, _, _, _), ref(Q), not sup(Q, _).
tval(Q, both) :- q_attempted(Q, _, _, _, _), sup(Q, _), ref(Q).
tval(Q, unk) :- q_attempted(Q, _, _, _, _), not sup(Q, _), not ref(Q).
tval(Q, true) :- q_completed(Q, _, _, _, _), sup(Q, _), not ref(Q).
tval(Q, false) :- q_completed(Q, _, _, _, _), ref(Q), not sup(Q, _).
tval(Q, both) :- q_completed(Q, _, _, _, _), sup(Q, _), ref(Q).
tval(Q, unk) :- q_completed(Q, _, _, _, _), not sup(Q, _), not ref(Q).

% ---- attempted(A, E, Actor, <= T)
sup(Q, F) :- q_attempted(Q, A, E, Act, T), attempt_fact(F, A, E2, Act, I),
             entmatch(E, E2), I <= T.
sup(Q, F) :- q_attempted(Q, A, E, Act, T), completed_fact(F, A, E2, Act, I),
             entmatch(E, E2), I <= T.
sup(Q, F) :- q_attempted(Q, A, E, Act, T), failed_fact(F, A, E2, Act, I),
             entmatch(E, E2), I <= T.
% absence refutation ONLY under the explicit premises
ref(Q) :- q_attempted(Q, A, E, Act, T), hist_complete, known_actors,
          not has_attempt_support(Q, A, E, Act, T).
has_attempt_support(Q, A, E, Act, T) :- q_attempted(Q, A, E, Act, T),
          attempt_fact(F, A, E2, Act, I), entmatch(E, E2), I <= T.
has_attempt_support(Q, A, E, Act, T) :- q_attempted(Q, A, E, Act, T),
          completed_fact(F, A, E2, Act, I), entmatch(E, E2), I <= T.
has_attempt_support(Q, A, E, Act, T) :- q_attempted(Q, A, E, Act, T),
          failed_fact(F, A, E2, Act, I), entmatch(E, E2), I <= T.

% ---- completed(A, E, Actor, <= T): completed facts, or trusted effects
%      whose call was an attempt of the same action.  Open world: no
%      refutation path at all.
sup(Q, F) :- q_completed(Q, A, E, Act, T), completed_fact(F, A, E2, Act, I),
             entmatch(E, E2), I <= T.
sup(Q, F) :- q_completed(Q, A, E, Act, T), effect_fact(F, _, E2, P, I, C),
             attempt_call(F2, A, E3, Act, _, C), entmatch(E, E2),
             entmatch(E, E3), I <= T.

% ---- row gathering for current-state queries (state / comparison)
gather(Q, E, P, T) :- q_state(Q, E, P, _, T).
gather(Q, E, P, T) :- q_cmp(Q, E, P, _, _, T).
qrow(Q, F, I) :- gather(Q, E, P, T), row(F, E, P, _, I), I <= T.
has_qrow(Q) :- qrow(Q, _, _).
qmax(Q, M) :- has_qrow(Q), M = #max { I : qrow(Q, _, I) }.
lrow(Q, F) :- qrow(Q, F, I), qmax(Q, I).
later_mut(Q) :- gather(Q, E, _, T), has_qrow(Q), qmax(Q, M),
                mut(J, E), M < J, J <= T.

% ---- state (LATEST, conservative)
lsup(Q, F) :- q_state(Q, E, P, V, _), lrow(Q, F), row(F, E, P, V2, _),
              vmatch(V, V2).
lref(Q, F) :- q_state(Q, E, P, V, _), lrow(Q, F), row(F, E, P, V2, _),
              vtype(V, V2), not vmatch(V, V2).
lsboth(Q) :- lsup(Q, _), lref(Q, _).
tval(Q, unk) :- q_state(Q, _, _, _, _), not has_qrow(Q).
tval(Q, both) :- q_state(Q, _, _, _, _), lsboth(Q).
tval(Q, unk) :- q_state(Q, _, _, _, _), has_qrow(Q), not lsboth(Q),
                    later_mut(Q).
tval(Q, false) :- q_state(Q, _, _, _, _), has_qrow(Q), not lsboth(Q),
                  not later_mut(Q), lref(Q, _), not lsup(Q, _).
tval(Q, true) :- q_state(Q, _, _, _, _), has_qrow(Q), not lsboth(Q),
                 not later_mut(Q), lsup(Q, _), not lref(Q, _).
tval(Q, unk) :- q_state(Q, _, _, _, _), has_qrow(Q), not lsboth(Q),
                    not later_mut(Q), not lsup(Q, _), not lref(Q, _).

% ---- state_hist (PAST existential: never false)
tval(Q, true) :- q_state_hist(Q, E, P, V, _), row(F, E, P, V2, _),
                 vmatch(V, V2).
tval(Q, unk) :- q_state_hist(Q, _, _, _, _), not hist_matched(Q).
hist_matched(Q) :- q_state_hist(Q, E, P, V, _), row(F, E, P, V2, _),
                   vmatch(V, V2).

% ---- comparison over the CURRENT state value (LATEST + staleness)
cmp_holds(eq, V, V) :- valsrc(V).
cmp_holds(ne, V1, V2) :- vtype(V1, V2), V1 != V2.
cmp_holds(lt, num(A), num(B)) :- valsrc(num(A)), valsrc(num(B)), A < B.
cmp_holds(le, num(A), num(B)) :- valsrc(num(A)), valsrc(num(B)), A <= B.
cmp_holds(gt, num(A), num(B)) :- valsrc(num(A)), valsrc(num(B)), A > B.
cmp_holds(ge, num(A), num(B)) :- valsrc(num(A)), valsrc(num(B)), A >= B.
cmp_type(eq, V1, V2) :- vtype(V1, V2).
cmp_type(ne, V1, V2) :- vtype(V1, V2).
cmp_type(lt, num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
cmp_type(le, num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
cmp_type(gt, num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
cmp_type(ge, num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
csup(Q, F) :- q_cmp(Q, E, P, Op, Rhs, _), lrow(Q, F), row(F, E, P, V2, _),
              cmp_holds(Op, V2, Rhs).
cref(Q, F) :- q_cmp(Q, E, P, Op, Rhs, _), lrow(Q, F), row(F, E, P, V2, _),
              cmp_type(Op, V2, Rhs), not cmp_holds(Op, V2, Rhs).
csboth(Q) :- csup(Q, _), cref(Q, _).
tval(Q, unk) :- q_cmp(Q, _, _, _, _, _), not has_qrow(Q).
tval(Q, both) :- q_cmp(Q, _, _, _, _, _), csboth(Q).
tval(Q, unk) :- q_cmp(Q, _, _, _, _, _), has_qrow(Q), not csboth(Q),
                    later_mut(Q).
tval(Q, false) :- q_cmp(Q, _, _, _, _, _), has_qrow(Q), not csboth(Q),
                  not later_mut(Q), cref(Q, _), not csup(Q, _).
tval(Q, true) :- q_cmp(Q, _, _, _, _, _), has_qrow(Q), not csboth(Q),
                 not later_mut(Q), csup(Q, _), not cref(Q, _).
tval(Q, unk) :- q_cmp(Q, _, _, _, _, _), has_qrow(Q), not csboth(Q),
                    not later_mut(Q), not csup(Q, _), not cref(Q, _).

% ---- cardinality (distinct event positions of matching action facts)
carddom(N) :- q_card(_, _, _, _, _, N, _).
cardc(C) :- ccount(_, C).
card_holds(at_least, C, N) :- carddom(N), cardc(C), C >= N.
card_holds(at_most, C, N) :- carddom(N), cardc(C), C <= N.
card_holds(exactly, C, N) :- carddom(N), cardc(C), C == N.
cidx(Q, I) :- q_card(Q, A, E, Act, _, _, T), attempt_fact(F, A, E2, Act, I),
              entmatch(E, E2), I <= T.
cidx(Q, I) :- q_card(Q, A, E, Act, _, _, T), completed_fact(F, A, E2, Act, I),
              entmatch(E, E2), I <= T.
cidx(Q, I) :- q_card(Q, A, E, Act, _, _, T), failed_fact(F, A, E2, Act, I),
              entmatch(E, E2), I <= T.
ccount(Q, C) :- q_card(Q, _, _, _, _, _, _), C = #count { I : cidx(Q, I) }.
tval(Q, true) :- q_card(Q, _, _, _, Op, N, _), ccount(Q, C),
                 card_holds(Op, C, N), hist_complete.
tval(Q, false) :- q_card(Q, _, _, _, Op, N, _), ccount(Q, C), hist_complete,
                  not card_holds(Op, C, N).
tval(Q, true) :- q_card(Q, _, _, _, at_least, N, _), ccount(Q, C),
                 C >= N, not hist_complete.
tval(Q, unk) :- q_card(Q, _, _, _, at_least, N, _), ccount(Q, C),
                    C < N, not hist_complete.
tval(Q, unk) :- q_card(Q, _, _, _, at_most, _, _), not hist_complete.
tval(Q, unk) :- q_card(Q, _, _, _, exactly, _, _), not hist_complete.
