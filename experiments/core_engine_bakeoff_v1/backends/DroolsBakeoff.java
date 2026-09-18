/** core_engine_bakeoff_v1 — backend: DROOLS harness (single-file, JRE-only).
 *
 * Reads a line-based payload (facts.txt) and a generated DRL program
 * (program.drl), builds a KieSession with 'declare'd fact types, inserts
 * the facts, fires all rules, and writes the derived answers (TV/SAF/WORLD)
 * to out.txt.  The four-valued connective tables and the world/consensus
 * fold live in this harness (Java); joins, constraints, accumulates
 * (latest-position, counts) and staleness are native DRL.
 *
 * Payload lines (pipe-separated; # = comment):
 *   NF|id|kind|actor|entity|predicate|tag|value|idx|region   (tag: num|str|bool|none)
 *   Q|id|kind|action|entity|actor|predicate|tag|expected|t
 *      (comparison: predicate = cmp predicate, expected = rhs)
 *      (cardinality: action = subject, expected = N)
 *   OBL|id|interp|ruleId|kind|root|targetQ|targetInv
 *   LEAFQ|node|qid|neg
 *   NOTN|node|inner
 *   ALLN|node|kid1,kid2,...
 *   ANYN|node|kid1,kid2,...
 *   MARK|interpId|markerText
 *   PREM|name                       (hist_complete / known_actors)
 *   TVQ|qid                         (probe request: emit TV)
 *   WORLD|interpId                  (world request: emit WORLD line)
 */
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class DroolsBakeoff {
    // ---- four-valued tables (indices: 0=t 1=f 2=b 3=u) ----
    static final String[] VALS = {"t", "f", "b", "u"};
    static final int[][] NEG = {{1,0,2,3}};  // per value index
    static int neg(int v) { return v == 0 ? 1 : v == 1 ? 0 : v; }
    static int conj(int a, int b) {
        // pos = AND(all pos bits), neg = OR(any neg bit); (t,f,b,u)->idx
        boolean pa = a == 0 || a == 2, na = a == 1 || a == 2;
        boolean pb = b == 0 || b == 2, nb = b == 1 || b == 2;
        boolean p = pa && pb, n = na || nb;
        return !p && !n ? 3 : p && !n ? 0 : !p && n ? 1 : 2;
    }
    static int disj(int a, int b) { return neg(conj(neg(a), neg(b))); }

    // ---- payload model ----
    static class NF {
        String id, kind, actor, entity, predicate, tag, value, region, callId;
        double num;
        int idx;
    }
    static class QDesc {
        String id, kind, action, entity, actor, predicate, tag, expected;
        int t;
    }
    static class Obl {
        String id, interp, ruleId, kind, root, targetQ;
        boolean targetInv;
    }
    static class Node {
        String id, kind, a, b;  // leaf: a=qid b=neg; not: a=inner; all/any: a=kids csv
    }

    public static void main(String[] args) throws Exception {
        String factsPath = args[0], drlPath = args[1], outPath = args[2];
        String drl = new String(Files.readAllBytes(Paths.get(drlPath)), StandardCharsets.UTF_8);

        List<NF> nfs = new ArrayList<>();
        List<QDesc> qs = new ArrayList<>();
        List<Obl> obls = new ArrayList<>();
        List<Node> nodes = new ArrayList<>();
        List<String[]> marks = new ArrayList<>();
        Set<String> prems = new HashSet<>();
        List<String> tvq = new ArrayList<>();
        List<String> worlds = new ArrayList<>();

        for (String line : Files.readAllLines(Paths.get(factsPath), StandardCharsets.UTF_8)) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] p = line.split("\\|", -1);
            switch (p[0]) {
                case "NF": { NF n = new NF(); n.id = p[1]; n.kind = p[2]; n.actor = p[3];
                    n.entity = p[4]; n.predicate = p[5]; n.tag = p[6]; n.value = p[7];
                    n.num = Double.parseDouble(p[8].isEmpty() ? "0" : p[8]);
                    n.idx = Integer.parseInt(p[9]); n.region = p[10];
                    n.callId = p.length > 11 ? p[11] : ""; nfs.add(n); break; }
                case "Q": { QDesc q = new QDesc(); q.id = p[1]; q.kind = p[2]; q.action = p[3];
                    q.entity = p[4]; q.actor = p[5]; q.predicate = p[6]; q.tag = p[7];
                    q.expected = p[8]; q.t = Integer.parseInt(p[9]); qs.add(q); break; }
                case "OBL": { Obl o = new Obl(); o.id = p[1]; o.interp = p[2]; o.ruleId = p[3];
                    o.kind = p[4]; o.root = p[5].isEmpty() ? null : p[5];
                    o.targetQ = p[6].isEmpty() ? null : p[6];
                    o.targetInv = "1".equals(p[7]); obls.add(o); break; }
                case "LEAFQ": { Node n = new Node(); n.id = p[1]; n.kind = "leaf"; n.a = p[2]; n.b = p[3]; nodes.add(n); break; }
                case "NOTN": { Node n = new Node(); n.id = p[1]; n.kind = "not"; n.a = p[2]; nodes.add(n); break; }
                case "ALLN": { Node n = new Node(); n.id = p[1]; n.kind = "all"; n.a = p[2]; nodes.add(n); break; }
                case "ANYN": { Node n = new Node(); n.id = p[1]; n.kind = "any"; n.a = p[2]; nodes.add(n); break; }
                case "MARK": marks.add(new String[]{p[1], p[2]}); break;
                case "PREM": prems.add(p[1]); break;
                case "TVQ": tvq.add(p[1]); break;
                case "WORLD": worlds.add(p[1]); break;
                default: throw new IllegalArgumentException("payload line: " + line);
            }
        }

        org.kie.api.KieServices ks = org.kie.api.KieServices.Factory.get();
        org.kie.api.builder.KieFileSystem kfs = ks.newKieFileSystem();
        kfs.write("src/main/resources/bakeoff/rules.drl", drl);
        org.kie.api.builder.KieBuilder kb = ks.newKieBuilder(kfs);
        kb.buildAll();
        if (kb.getResults().hasMessages(org.kie.api.builder.Message.Level.ERROR)) {
            try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(
                    Paths.get(outPath), StandardCharsets.UTF_8))) {
                out.println("DRLERROR|" + kb.getResults().getMessages().toString()
                        .replace("\n", " ").substring(0, Math.min(2000,
                        kb.getResults().getMessages().toString().length())));
            }
            return;
        }
        org.kie.api.runtime.KieContainer kc =
                ks.newKieContainer(kb.getKieModule().getReleaseId());
        org.kie.api.runtime.KieSession session = kc.newKieSession();
        ClassLoader cl = kc.getClassLoader();

        // insert facts through the generated declared types
        Class<?> nfC = cl.loadClass("bakeoff.NF");
        Class<?> qC = cl.loadClass("bakeoff.Q");
        Class<?> nodeC = cl.loadClass("bakeoff.NODE");
        Class<?> oblC = cl.loadClass("bakeoff.OBL");
        Class<?> premC = cl.loadClass("bakeoff.PREM");
        Class<?> markC = cl.loadClass("bakeoff.MARK");
        for (NF n : nfs) {
            Object o = nfC.getDeclaredConstructor().newInstance();
            set(nfC, o, "Id", n.id); set(nfC, o, "Kind", n.kind);
            set(nfC, o, "Actor", n.actor); set(nfC, o, "Entity", n.entity);
            set(nfC, o, "Predicate", n.predicate); set(nfC, o, "Tag", n.tag);
            set(nfC, o, "Value", n.value); set(nfC, o, "NumVal", n.num);
            set(nfC, o, "Idx", n.idx); set(nfC, o, "CallId", n.callId);
            set(nfC, o, "Region", n.region);
            session.insert(o);
        }
        for (QDesc q : qs) {
            Object o = qC.getDeclaredConstructor().newInstance();
            set(qC, o, "Id", q.id); set(qC, o, "Kind", q.kind);
            set(qC, o, "Action", q.action); set(qC, o, "Entity", q.entity);
            set(qC, o, "Actor", q.actor); set(qC, o, "Predicate", q.predicate);
            set(qC, o, "Tag", q.tag); set(qC, o, "Expected", q.expected);
            set(qC, o, "T", q.t);
            session.insert(o);
        }
        for (Node n : nodes) {
            Object o = nodeC.getDeclaredConstructor().newInstance();
            set(nodeC, o, "Id", n.id); set(nodeC, o, "Kind", n.kind);
            set(nodeC, o, "A", n.a); set(nodeC, o, "B", n.b == null ? "" : n.b);
            session.insert(o);
        }
        for (Obl o0 : obls) {
            Object o = oblC.getDeclaredConstructor().newInstance();
            set(oblC, o, "Id", o0.id); set(oblC, o, "Interp", o0.interp);
            set(oblC, o, "RuleId", o0.ruleId); set(oblC, o, "Kind", o0.kind);
            set(oblC, o, "Root", o0.root == null ? "" : o0.root);
            set(oblC, o, "TargetQ", o0.targetQ == null ? "" : o0.targetQ);
            set(oblC, o, "TargetInv", o0.targetInv);
            session.insert(o);
        }
        for (String prem : prems) {
            Object o = premC.getDeclaredConstructor().newInstance();
            set(premC, o, "Name", prem);
            session.insert(o);
        }
        for (String[] m : marks) {
            Object o = markC.getDeclaredConstructor().newInstance();
            set(markC, o, "Interp", m[0]); set(markC, o, "Text", m[1]);
            session.insert(o);
        }
        int fired = session.fireAllRules();

        // ---- collect answers
        Map<String, String> tv = new LinkedHashMap<>();
        Map<String, String> saf = new LinkedHashMap<>();
        Class<?> tvC = cl.loadClass("bakeoff.TV");
        Class<?> safC = cl.loadClass("bakeoff.SAF");
        for (Object o : session.getObjects()) {
            if (o.getClass().getName().equals("bakeoff.TV")) {
                tv.put((String) get(tvC, o, "Qid"), (String) get(tvC, o, "V"));
            } else if (o.getClass().getName().equals("bakeoff.SAF")) {
                saf.put((String) get(safC, o, "Oid"), (String) get(safC, o, "V"));
            }
        }
        StringBuilder out = new StringBuilder();
        out.append("FIRED|").append(fired).append('\n');
        for (String qid : tvq) {
            out.append("TV|").append(qid).append('|')
               .append(tv.getOrDefault(qid, "u")).append('\n');
        }
        for (String interp : worlds) {
            List<Integer> vals = new ArrayList<>();
            boolean marker = false;
            for (Obl o : obls) {
                if (!o.interp.equals(interp)) continue;
                String v = saf.get(o.id);
                if (v == null) continue;
                vals.add(Arrays.asList(VALS).indexOf(v));
            }
            for (String[] m : marks) {
                if (m[0].equals(interp)) marker = true;
            }
            int ev;  // world error value index
            if (vals.contains(1)) ev = 0;            // some safety f -> error t
            else if (vals.contains(2)) ev = 2;       // both
            else if (vals.contains(3) || marker) ev = 3;
            else if (vals.isEmpty()) ev = 1;         // no obligations: conj()=t
            else ev = 1;                             // all t
            out.append("WORLD|").append(interp).append('|').append(VALS[ev]).append('\n');
        }
        for (String qid : tvq) { /* TV lines already emitted */ }
        for (Map.Entry<String, String> e : saf.entrySet()) {
            out.append("SAF|").append(e.getKey()).append('|').append(e.getValue()).append('\n');
        }
        Files.write(Paths.get(outPath), out.toString().getBytes(StandardCharsets.UTF_8));
        session.dispose();
    }

    static void set(Class<?> c, Object o, String field, Object v) throws Exception {
        Class<?> t = v.getClass();
        if (v instanceof Integer) t = int.class;
        if (v instanceof Boolean) t = boolean.class;
        try {
            c.getMethod("set" + field, t).invoke(o, v);
        } catch (NoSuchMethodException e) {
            for (java.lang.reflect.Method m : c.getMethods()) {
                if (m.getName().equals("set" + field) && m.getParameterCount() == 1) {
                    if (t == int.class && m.getParameterTypes()[0] == long.class) {
                        m.invoke(o, (long) (Integer) v); return;
                    }
                    m.invoke(o, v); return;
                }
            }
            throw e;
        }
    }

    static Object get(Class<?> c, Object o, String field) throws Exception {
        for (java.lang.reflect.Method m : c.getMethods()) {
            if (m.getName().equals("get" + field) && m.getParameterCount() == 0) {
                return m.invoke(o);
            }
        }
        throw new NoSuchMethodException("get" + field);
    }
}
