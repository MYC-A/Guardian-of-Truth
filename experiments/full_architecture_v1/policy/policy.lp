% ================= four-valued composition algebra =================
% (shared by the policy folds: condition trees, obligation safety, world
%  error values; the EVIDENCE module derives tval facts, the POLICY module
%  composes them with these tables — directive §15: policy reads only the
%  normalized evidence predicate tval/2 plus its own data and algebra)

% ---- four-valued connective tables
neg(true, false). neg(false, true). neg(both, both). neg(unk, unk).
conj(true, true, true).
conj(true, false, false).
conj(true, both, both).
conj(true, unk, unk).
tvdom(true). tvdom(false). tvdom(both). tvdom(unk).
conj(false, X, false) :- tvdom(X).
conj(both, true, both).
conj(both, false, false).
conj(both, both, both).
conj(both, unk, both).
conj(unk, true, unk).
conj(unk, false, false).
conj(unk, both, both).
conj(unk, unk, unk).
disj(A, B, C) :- neg(A, NA), neg(B, NB), conj(NA, NB, NAB), neg(NAB, C).

% ==================== condition trees (recursive native fold) ==============

cval(N, V) :- cnode(N, leaf), cleaf(N, Q, 0), tval(Q, V).
cval(N, V) :- cnode(N, leaf), cleaf(N, Q, 1), tval(Q, W), neg(W, V).
cval(N, V) :- cnode(N, negnode), cnot(N, M), cval(M, W), neg(W, V).

% conjunction fold over ordered children (recursion)
fold(N, 0, V) :- cchild(N, 0, M), cval(M, V).
fold(N, P, V) :- cchild(N, P, M), fold(N, P1, V1), P = P1 + 1,
                 cval(M, V2), conj(V1, V2, V).
cval(N, V) :- cnode(N, all), lastchild(N, P), fold(N, P, V).
% disjunction fold over ordered children (recursion)
foldo(N, 0, V) :- cchild(N, 0, M), cval(M, V).
foldo(N, P, V) :- cchild(N, P, M), foldo(N, P1, V1), P = P1 + 1,
                  cval(M, V2), disj(V1, V2, V).
cval(N, V) :- cnode(N, any), lastchild(N, P), foldo(N, P, V).

% ===================== obligations, worlds, consensus ======================

1 { active(I) : interp(I) } 1.

antv(O, V) :- obl(O, _, _, _), obl_root(O, N), cval(N, V).
antv(O, true) :- obl(O, _, _, _), not obl_root(O, _).

% target atom value
tvv(O, true) :- obl(O, _, _, _), obl_target_inv(O).
tvv(O, V) :- obl(O, _, _, _), obl_target_q(O, Q), tval(Q, V).

% safety = NOT(antecedent AND NOT-required):
%   FORBID (required = NOT target):   saf = NOT(ant AND target)
%   REQUIRE (required = target):      saf = NOT(ant AND NOT target)
saf(O, V) :- obl(O, _, _, _), obl_kind(O, forbid), antv(O, A), tvv(O, T),
             conj(A, T, C), neg(C, V).
saf(O, V) :- obl(O, _, _, _), obl_kind(O, require), antv(O, A), tvv(O, T),
             neg(T, NT), conj(A, NT, C), neg(C, V).

wfalse(I) :- active(I), saf(O, false), obl(O, I, _, _).
wboth(I) :- active(I), saf(O, both), obl(O, I, _, _).
wunk1(I) :- active(I), saf(O, unk), obl(O, I, _, _).
wunk2(I) :- active(I), marker(I, _).
has_obl(I) :- active(I), obl(_, I, _, _).
werr(I, true) :- active(I), wfalse(I).
werr(I, both) :- active(I), wboth(I), not wfalse(I).
werr(I, unk) :- active(I), not wfalse(I), not wboth(I), wunk1(I).
werr(I, unk) :- active(I), not wfalse(I), not wboth(I), wunk2(I).
werr(I, false) :- active(I), not wfalse(I), not wboth(I), not wunk1(I),
                  not wunk2(I), has_obl(I).
werr(I, false) :- active(I), not wfalse(I), not wboth(I), not wunk1(I),
                  not wunk2(I), not has_obl(I).
