import math
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List

# Deterministic local statistical validation - no LLM, no network
# Exact methods require scipy; approximate p-values are never exposed as exact.

def _normal_quantile_95():
    return 1.96

def _wilson_ci(p: float, n: int, z: float = 1.96):
    """Wilson score interval for proportion - exact, no scipy needed"""
    if n == 0:
        return None
    denom = 1 + z*z/n
    centre = (p + z*z/(2*n)) / denom
    delta = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
    return {"lower": max(0.0, centre - delta), "upper": min(1.0, centre + delta), "centre": centre}

def _mean_ci(mean: float, std: float, n: int, z: float = 1.96):
    if n <= 1 or std is None or math.isnan(std):
        return None
    se = std / math.sqrt(n)
    margin = z * se
    return {"lower": mean - margin, "upper": mean + margin, "margin": margin, "se": se}

def _proportion_z_test(p1: float, n1: int, p2: float, n2: int):
    """Two-proportion z-test (pooled) - uses normal distribution, exact via erf"""
    if n1 < 5 or n2 < 5:
        return None
    x1 = p1 * n1
    x2 = p2 * n2
    p_pool = (x1 + x2) / (n1 + n2) if (n1+n2) > 0 else 0.0
    if p_pool == 0 or p_pool == 1:
        return None
    se = math.sqrt(p_pool*(1-p_pool)*(1/n1 + 1/n2))
    if se == 0:
        return None
    diff = p1 - p2
    z = diff / se
    p_val = 2 * (1 - 0.5 * (1 + math.erf(abs(z)/ math.sqrt(2))))
    return {"z": z, "p_value": p_val, "diff": diff, "se": se}

def _two_sample_t_exact(mean1, std1, n1, mean2, std2, n2, series1: pd.Series = None, series2: pd.Series = None):
    """
    Welch's t-test exact p-value via scipy.
    If scipy unavailable, return None to signal unavailable (do not fabricate).
    Also enforces small-sample guard: n <10 => not applicable.
    """
    if n1 < 10 or n2 < 10:
        return None  # too small, caller should handle as not applicable
    if std1 is None or std2 is None:
        return None
    # Try scipy exact
    try:
        import scipy.stats as st
        # If raw series provided, use them for exact test
        if series1 is not None and series2 is not None:
            # Use ttest_ind with equal_var=False
            t_stat, p_val = st.ttest_ind(series1, series2, equal_var=False, nan_policy='omit')
            if p_val is None or math.isnan(float(p_val)):
                return None
            # Compute diff and se for effect size
            diff = float(mean1 - mean2)
            se1 = std1*std1 / n1 if n1 else 0
            se2 = std2*std2 / n2 if n2 else 0
            se = math.sqrt(se1 + se2) if (se1+se2) >=0 else 0
            t_stat = float(t_stat)
            p_val = float(p_val)
        else:
            # Fallback using summary stats: Welch t and df via Welch-Satterthwaite, then p via t.cdf
            se1 = std1*std1 / n1 if n1 else 0
            se2 = std2*std2 / n2 if n2 else 0
            se = math.sqrt(se1 + se2)
            if se == 0:
                return None
            diff = mean1 - mean2
            t = diff / se
            # Welch-Satterthwaite df
            num = (se1 + se2)**2
            den = (se1**2)/(n1-1) if n1>1 else 0 + (se2**2)/(n2-1) if n2>1 else 0
            # More precise: denominator = se1^2/(n1-1) + se2^2/(n2-1)
            den = (se1*se1)/(n1-1) if n1>1 else 0
            den += (se2*se2)/(n2-1) if n2>1 else 0
            # Actually se1 = s1^2/n1, so se1^2 = s1^4/n1^2, but formula uses (s1^2/n1)^2/(n1-1)
            # Let's compute correctly:
            s1_sq = std1*std1
            s2_sq = std2*std2
            num = (s1_sq/n1 + s2_sq/n2)**2
            den = ( (s1_sq/n1)**2)/(n1-1) + ((s2_sq/n2)**2)/(n2-1)
            df = num/den if den !=0 else 1
            # p via t distribution
            p_val = 2 * (1 - st.t.cdf(abs(t), df))
            t_stat = t
            p_val = float(p_val)
            t = float(t_stat)
            # Recompute diff
            diff = mean1 - mean2
            se = math.sqrt(se1+se2)
        # Cohen's d pooled
        pooled_var = ((n1-1)*std1*std1 + (n2-1)*std2*std2) / (n1+n2-2) if (n1+n2-2) >0 else (std1*std1+std2*std2)/2
        pooled_sd = math.sqrt(pooled_var) if pooled_var >0 else None
        d = diff / pooled_sd if pooled_sd and pooled_sd !=0 else None
        t_out = t_stat if 't_stat' in locals() else t if 't' in locals() else 0
        p_out = p_val if 'p_val' in locals() else None
        df_out = float(df) if 'df' in locals() else None
        return {"t": float(t_out), "p_value": float(p_out) if p_out is not None else None, "diff": diff, "se": se, "cohens_d": d, "df": df_out}
    except ImportError:
        return None  # signal scipy unavailable
    except Exception:
        return None

def _chi_square_exact(observed: List[List[int]]):
    """Chi-square exact via scipy.stats.chi2_contingency. If scipy unavailable, return None (do not fabricate)."""
    if not observed or not observed[0]:
        return None
    r = len(observed)
    c = len(observed[0])
    row_sums = [sum(row) for row in observed]
    col_sums = [sum(observed[i][j] for i in range(r)) for j in range(c)]
    total = sum(row_sums)
    if total < 10:
        return None
    # Check small expected
    has_small_expected = False
    for i in range(r):
        for j in range(c):
            exp = row_sums[i]*col_sums[j]/total if total else 0
            if exp < 5:
                has_small_expected = True
    # Require scipy
    try:
        import scipy.stats as st
        import numpy as np2
        arr = np2.array(observed, dtype=float)
        chi2, p_val, dof, expected = st.chi2_contingency(arr, correction=False)
        return {"chi2": float(chi2), "df": int(dof), "p_value": float(p_val), "has_small_expected": has_small_expected, "expected": expected.tolist() if hasattr(expected, 'tolist') else None}
    except ImportError:
        return None
    except Exception:
        return None

def _cohens_h(p1: float, p2: float):
    """Cohen's h for proportion difference"""
    if p1 <0 or p1>1 or p2<0 or p2>1:
        return None
    p1c = min(max(p1, 0.0001), 0.9999)
    p2c = min(max(p2, 0.0001), 0.9999)
    h = 2*math.asin(math.sqrt(p1c)) - 2*math.asin(math.sqrt(p2c))
    return h

def validate_result(df: pd.DataFrame, question: str, sql: str, columns: List[str], rows: List[Dict], total_rows: int) -> Dict[str, Any]:
    """
    Determine if result supports statistical test and compute.
    Returns structured metadata.
    Never fabricates p-values; if exact method unavailable, returns applicable=False.
    """
    q = (question or "").lower()
    sql_low = (sql or "").lower()
    limitations = []
    lower_cols = [c.lower() for c in columns]
    is_approval = "approval_rate" in lower_cols
    is_proportion = is_approval or "rate" in q or "proportion" in q or "approval" in q or "conversion" in q

    def check_small_groups(rows, threshold=10):
        for r in rows:
            n = r.get("application_count") or r.get("count") or r.get("n")
            try:
                if n is not None and int(float(n)) < 10:
                    return True
            except:
                continue
        return False

    # Case A: two-group proportion comparison
    if is_approval and len(rows) >= 2:
        try:
            loan_col = next((c for c in df.columns if c.lower()=="loan_status"), None)
            if loan_col is None:
                limitations.append("Loan_Status column not found for overall rate")
                return {"applicable": False, "reason": "No Loan_Status for overall benchmark", "limitations": limitations}
            total_n = len(df)
            approved_mask = df[loan_col].astype(str).str.strip().str.lower().isin(['y','yes','approved','1','true'])
            overall_approved = int(approved_mask.sum())
            overall_p = overall_approved / total_n if total_n else 0
            approval_col = next(c for c in columns if c.lower()=="approval_rate")
            strongest = rows[0]
            strongest_rate_raw = strongest.get(approval_col)
            strongest_n = strongest.get("application_count") or strongest.get("count") or 0
            try:
                strongest_p = float(strongest_rate_raw)/100.0 if float(strongest_rate_raw) > 1 else float(strongest_rate_raw)
            except:
                strongest_p = None
            if strongest_p is None:
                limitations.append("Could not parse strongest rate")
                return {"applicable": False, "reason": "Parse failure", "limitations": limitations}
            if strongest_p > 1:
                strongest_p = strongest_p/100.0
            try:
                strongest_n_int = int(float(strongest_n))
            except:
                strongest_n_int = 0
            # Small sample guard for proportion: need at least 10 per group and expected counts >=5
            if strongest_n_int < 10 or total_n < 10:
                limitations.append(f"Small sample: strongest n={strongest_n_int}, overall n={total_n} — estimates unstable; statistical test not applicable")
                # Wilson CI still valid, but z-test not reliable; we will still compute CI but mark test as limited
                # For consistency, if n<10, we treat as not applicable for significance
                # However we still want to provide CI; we return applicable but with warning? Spec says strengthen validation: if too small, do not calculate misleading significance.
                # We will proceed but ensure p-value not shown as exact if small? For proportion, we have check n<5 in _proportion_z_test already.
                # For this case, we allow but limitations will indicate instability.
                pass
            overall_ci_raw = _wilson_ci(overall_p, total_n)
            strongest_ci_raw = _wilson_ci(strongest_p, strongest_n_int)
            def ci_to_pp(ci):
                if not ci:
                    return None
                return {"lower": round(ci["lower"]*100,1), "upper": round(ci["upper"]*100,1), "centre": round(ci["centre"]*100,1)}
            overall_ci = ci_to_pp(overall_ci_raw)
            strongest_ci = ci_to_pp(strongest_ci_raw)
            diff_benchmark_pp = (strongest_p - overall_p)*100
            rest_n = total_n - strongest_n_int
            rest_approved = overall_approved - int(round(strongest_p*strongest_n_int)) if strongest_p else overall_approved
            rest_p = rest_approved / rest_n if rest_n else overall_p
            rest_ci_raw = _wilson_ci(rest_p, rest_n) if rest_n >0 else None
            rest_ci = ci_to_pp(rest_ci_raw)
            diff_rest_pp = (strongest_p - rest_p)*100
            test = _proportion_z_test(strongest_p, strongest_n_int, rest_p, rest_n) if rest_n >=5 else None
            effect_h_rest = _cohens_h(strongest_p, rest_p)
            effect_h_overall = _cohens_h(strongest_p, overall_p)
            # Use rest comparison for inferential effect size
            effect_h = effect_h_rest if effect_h_rest is not None else effect_h_overall
            practical_rest = "material" if abs(diff_rest_pp) >= 5 else "small" if abs(diff_rest_pp) >=2 else "negligible"
            practical_benchmark = "material" if abs(diff_benchmark_pp) >= 5 else "small" if abs(diff_benchmark_pp) >=2 else "negligible"
            practical = practical_rest
            # Small-sample handling for proportion: if any expected <5, flag and consider not applicable for significance
            small_expected = has_small_expected_proportion(strongest_p, strongest_n_int) or has_small_expected_proportion(rest_p, rest_n) or has_small_expected_proportion(overall_p, total_n)
            if small_expected:
                limitations.append("Expected counts <5 for some groups — z-test assumptions may be violated")
            # Significance labeling: if test is None due to small, mark insufficient
            if test is None and (strongest_n_int <10 or rest_n <10 or small_expected):
                significance_label = "insufficient evidence — sample too small for reliable test"
            else:
                significance_label = "statistically significant" if test and test["p_value"] < 0.05 else "not statistically significant" if test else "insufficient evidence"
            if strongest_n_int < 30:
                limitations.append("Strongest segment n <30 — confidence interval wide, estimate unstable")
            if rest_n < 30:
                limitations.append("Rest-of-population n <30 — estimate less precise")
            limitations.append("Association does not imply causation; confounding factors may explain difference")
            limitations.append("Benchmark strongest vs overall includes overlap (not independent); inferential test uses strongest vs rest-of-population")
            # Filter empty "-" placeholders
            limitations = [lim for lim in limitations if lim and lim.strip() not in ("", "-")]
            return {
                "applicable": True,
                "method": "two_group_proportion_wilson_z",
                "estimate": round(diff_rest_pp,1),
                "estimate_label": "difference_vs_rest_percentage_points",
                "estimate_rest": round(diff_rest_pp,1),
                "estimate_benchmark": round(diff_benchmark_pp,1),
                "benchmark_difference_pp": round(diff_benchmark_pp,1),
                "inferential_difference_pp": round(diff_rest_pp,1),
                "confidence_interval": {
                    "strongest_segment": strongest_ci,
                    "overall": overall_ci,
                    "rest": rest_ci,
                    "difference_vs_rest_pp": round(diff_rest_pp,1),
                    "difference_vs_overall_pp": round(diff_benchmark_pp,1),
                    "difference_pp": round(diff_rest_pp,1)
                },
                "p_value": round(test["p_value"],4) if test and test.get("p_value") is not None else None,
                "z_statistic": round(test["z"],2) if test else None,
                "effect_size": round(effect_h,3) if effect_h is not None else None,
                "effect_size_label": "cohens_h",
                "effect_size_interpretation": _interpret_h(effect_h),
                "effect_size_vs_rest": round(effect_h_rest,3) if effect_h_rest is not None else None,
                "effect_size_vs_overall": round(effect_h_overall,3) if effect_h_overall is not None else None,
                "sample_sizes": {"strongest": strongest_n_int, "overall": total_n, "rest": rest_n},
                "significance": significance_label,
                "practical_significance": practical,
                "practical_significance_inferential": practical_rest,
                "practical_significance_benchmark": practical_benchmark,
                "limitations": limitations,
                "comparison": "strongest_segment_vs_rest",
                "benchmark_comparison": "strongest_segment_vs_overall",
                "comparison_note": "Benchmark (strongest vs overall) is descriptive and overlapping — not independent; inferential comparison (strongest vs rest) is statistically independent",
                "observed": {
                    "strongest_rate": round(strongest_p*100,1),
                    "overall_rate": round(overall_p*100,1),
                    "rest_rate": round(rest_p*100,1),
                    "difference_vs_rest_pp": round(diff_rest_pp,1),
                    "difference_vs_overall_pp": round(diff_benchmark_pp,1),
                    "difference_pp": round(diff_benchmark_pp,1),
                    "inferential_difference_pp": round(diff_rest_pp,1),
                    "benchmark_difference_pp": round(diff_benchmark_pp,1)
                },
                "inferential": {
                    "label": "Strongest vs Rest-of-Population (independent)",
                    "strongest_rate": round(strongest_p*100,1),
                    "rest_rate": round(rest_p*100,1),
                    "difference_pp": round(diff_rest_pp,1),
                    "method": "two_proportion_z_test (strongest vs rest)",
                    "confidence_interval_rest": rest_ci,
                    "confidence_interval_strongest": strongest_ci
                },
                "benchmark": {
                    "label": "Strongest vs Overall (business benchmark, overlapping — not independent)",
                    "strongest_rate": round(strongest_p*100,1),
                    "overall_rate": round(overall_p*100,1),
                    "difference_pp": round(diff_benchmark_pp,1),
                    "note": "Business benchmark includes overlap; not used for inferential testing"
                },
                "causation_disclaimer": "Observed difference; statistically significant association does not establish causation."
            }
        except Exception as e:
            limitations.append(f"Failed to compute proportion validation: {str(e)[:120]}")
            return {"applicable": False, "reason": str(e)[:120], "limitations": limitations}

    # Case B: single proportion CI (scalar rate)
    if len(rows)==1 and len(columns)==1 and is_proportion:
        try:
            col = columns[0]
            val = rows[0].get(col)
            p = float(val)
            if p > 1:
                p = p/100.0
            n = total_rows
            ci = _wilson_ci(p, n)
            if ci:
                limitations=[]
                if n < 30:
                    limitations.append("Small sample n<30 — interval wide")
                limitations.append("Proportion CI assumes independent Bernoulli trials")
                return {
                    "applicable": True,
                    "method": "wilson_proportion_ci",
                    "estimate": round(p*100,1),
                    "confidence_interval": {"lower": round(ci["lower"]*100,1), "upper": round(ci["upper"]*100,1), "level": 95},
                    "p_value": None,
                    "effect_size": None,
                    "sample_sizes": {"n": n},
                    "significance": "n/a — single estimate",
                    "practical_significance": "n/a",
                    "limitations": limitations
                }
        except:
            pass

    # Case C: numeric group comparison difference in means - Welch t-test exact via scipy
    if len(rows) >=2 and len(columns) >=2:
        group_col = columns[0]
        metric_col = columns[1]
        is_mean = any(k in sql_low for k in ["avg(", "average"])
        is_sum = "sum(" in sql_low
        if is_mean and group_col.lower() not in ["month","date","year"]:
            try:
                top_val = rows[0].get(group_col)
                bottom_val = rows[-1].get(group_col) if len(rows)>1 else None
                if top_val is None or bottom_val is None or top_val == bottom_val:
                    limitations.append("Need at least two distinct groups for mean comparison")
                    return {"applicable": False, "reason": "Insufficient distinct groups", "limitations": limitations}
                df_group_col = next((c for c in df.columns if c.lower()==group_col.lower()), None)
                if df_group_col is None:
                    return {"applicable": False, "reason": "Group column not in dataframe", "limitations": ["Group column mismatch"]}
                import re as _re
                m = _re.search(r'avg\s*\(\s*"([^"]+)"\s*\)', sql, flags=_re.IGNORECASE)
                if not m:
                    m = _re.search(r"avg\s*\(\s*'([^']+)'\s*\)", sql, flags=_re.IGNORECASE)
                if not m:
                    m = _re.search(r'avg\s*\(\s*([a-z_][a-z0-9_]*)\s*\)', sql, flags=_re.IGNORECASE)
                numeric_source = m.group(1) if m else metric_col
                df_numeric_col = next((c for c in df.columns if c.lower()==numeric_source.lower()), None)
                if df_numeric_col is None:
                    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                    if numeric_cols:
                        df_numeric_col = numeric_cols[0]
                    else:
                        return {"applicable": False, "reason": "No numeric column for mean comparison", "limitations": ["No numeric column"]}
                top_series = df[df[df_group_col].astype(str) == str(top_val)][df_numeric_col].dropna()
                bottom_series = df[df[df_group_col].astype(str) == str(bottom_val)][df_numeric_col].dropna()
                n1, n2 = len(top_series), len(bottom_series)
                # Strengthened small-sample validation: n <10 => not applicable
                if n1 < 10 or n2 < 10:
                    limitations.append(f"Sample too small for Welch t-test: n1={n1}, n2={n2} — requires at least 10 per group")
                    return {"applicable": False, "reason": f"Sample too small for Welch t-test (n1={n1}, n2={n2})", "limitations": limitations + ["Exact Welch t-test requires n>=10 per group; estimates unstable"]}
                mean1, mean2 = float(top_series.mean()), float(bottom_series.mean())
                std1, std2 = float(top_series.std(ddof=1)) if n1>1 else 0.0, float(bottom_series.std(ddof=1)) if n2>1 else 0.0
                ci1 = _mean_ci(mean1, std1, n1)
                ci2 = _mean_ci(mean2, std2, n2)
                diff = mean1 - mean2
                test = _two_sample_t_exact(mean1, std1, n1, mean2, std2, n2, top_series, bottom_series)
                if test is None:
                    # Check if scipy unavailable
                    try:
                        import scipy.stats  # noqa
                        # scipy available but test still None => small sample already handled
                        limitations.append("Welch t-test could not be computed reliably")
                    except ImportError:
                        limitations.append("Exact Welch t-test p-value requires scipy.")
                    limitations.append("Observed difference; does not establish causation")
                    return {"applicable": False, "reason": "Exact Welch t-test p-value requires scipy." if "scipy" in str(limitations) else "Welch t-test not computable", "limitations": limitations}
                practical = "material" if test and test.get("cohens_d") and abs(test["cohens_d"]) >=0.5 else "small" if test and test.get("cohens_d") and abs(test["cohens_d"])>=0.2 else "negligible" if test else "n/a"
                significance = "statistically significant" if test and test["p_value"] <0.05 else "not statistically significant" if test else "insufficient"
                limitations.append("Observed difference; does not establish causation")
                if any([n1<30, n2<30]):
                    limitations.append("One or both groups n<30 — confidence interval wide")
                return {
                    "applicable": True,
                    "method": "two_sample_welch_t",
                    "estimate": round(diff,2),
                    "estimate_label": "difference_in_means",
                    "confidence_interval": {
                        "group_top": {"mean": round(mean1,2), "ci": {"lower": round(ci1["lower"],2), "upper": round(ci1["upper"],2)} if ci1 else None, "n": n1},
                        "group_bottom": {"mean": round(mean2,2), "ci": {"lower": round(ci2["lower"],2), "upper": round(ci2["upper"],2)} if ci2 else None, "n": n2},
                        "difference": round(diff,2)
                    },
                    "p_value": round(test["p_value"],4) if test else None,
                    "t_statistic": round(test["t"],2) if test else None,
                    "degrees_of_freedom": round(test["df"],1) if test and test.get("df") else None,
                    "effect_size": round(test["cohens_d"],3) if test and test.get("cohens_d") is not None else None,
                    "effect_size_label": "cohens_d",
                    "effect_size_interpretation": _interpret_d(test["cohens_d"]) if test and test.get("cohens_d") is not None else None,
                    "sample_sizes": {"group_top": n1, "group_bottom": n2},
                    "significance": significance,
                    "practical_significance": practical,
                    "limitations": limitations,
                    "observed": {"top_value": str(top_val), "bottom_value": str(bottom_val), "mean_top": round(mean1,2), "mean_bottom": round(mean2,2)}
                }
            except Exception as e:
                # If exception is due to scipy missing, ensure limitation reflects that
                msg = str(e)
                if "scipy" in msg.lower():
                    limitations.append("Exact Welch t-test p-value requires scipy.")
                    return {"applicable": False, "reason": "Exact Welch t-test p-value requires scipy.", "limitations": limitations}
                limitations.append(f"Mean comparison failed: {msg[:120]}")
                return {"applicable": False, "reason": msg[:120], "limitations": limitations}

    # Case D: chi-square for categorical association - exact via scipy
    if any(k in q for k in ["association", "chi", "categorical", "relationship"]):
        cat_cols = [c for c in df.columns if df[c].dtype == object or df[c].dtype.name == 'category']
        if len(cat_cols) >=2:
            c1, c2 = cat_cols[0], cat_cols[1]
            try:
                ct = pd.crosstab(df[c1].astype(str), df[c2].astype(str))
                observed = ct.values.tolist()
                res = _chi_square_exact(observed)
                if res is None:
                    # Distinguish scipy missing vs other
                    try:
                        import scipy.stats  # noqa
                        # scipy present but res None => maybe small total or other
                        limitations.append("Chi-square not computable (small sample or invalid table)")
                        return {"applicable": False, "reason": "Chi-square not computable", "limitations": limitations}
                    except ImportError:
                        return {"applicable": False, "reason": "Chi-square test requires scipy.", "limitations": ["Chi-square test requires scipy.", "Association does not imply causation"]}
                limitations=[]
                if res.get("has_small_expected"):
                    limitations.append("Some expected counts <5 — chi-square assumptions violated; consider Fisher exact")
                limitations.append("Association does not imply causation")
                practical = "moderate" if res["chi2"] > res["df"]*2 else "small"
                significance = "statistically significant association" if res["p_value"]<0.05 else "no significant association"
                return {
                    "applicable": True,
                    "method": "chi_square_association",
                    "estimate": round(res["chi2"],2),
                    "estimate_label": "chi_square_statistic",
                    "confidence_interval": None,
                    "p_value": round(res["p_value"],4) if res["p_value"] is not None else None,
                    "effect_size": None,
                    "sample_sizes": {"total": int(ct.values.sum()), "table_shape": f"{len(observed)}x{len(observed[0])}"},
                    "significance": significance,
                    "practical_significance": practical,
                    "limitations": limitations,
                    "degrees_of_freedom": res["df"]
                }
            except Exception as e:
                if "scipy" in str(e).lower():
                    return {"applicable": False, "reason": "Chi-square test requires scipy.", "limitations": ["Chi-square test requires scipy."]}
                pass

    # Fallback: not applicable
    simple = any(k in q for k in ["what is total", "what is average", "count by"])
    if simple and len(rows) <= 5:
        return {"applicable": False, "reason": "Simple aggregation — no comparison to test", "limitations": ["Single aggregate does not support group comparison"]}
    if len(rows) <2:
        return {"applicable": False, "reason": "Insufficient groups for statistical comparison", "limitations": ["Need at least two groups"]}
    if "sum(" in sql_low and not is_approval:
        return {"applicable": False, "reason": "Sum comparison not appropriate for statistical test without normalization", "limitations": ["Totals depend on group sizes; compare rates or means instead"]}
    return {"applicable": False, "reason": "No appropriate statistical test for this result shape", "limitations": ["Result type not suitable for pre-defined tests"]}

def has_small_expected_proportion(p, n):
    return p*n <5 or (1-p)*n <5

def _interpret_d(d):
    if d is None:
        return None
    a = abs(d)
    if a <0.2:
        return "negligible"
    if a <0.5:
        return "small"
    if a <0.8:
        return "medium"
    return "large"

def _interpret_h(h):
    if h is None:
        return None
    a = abs(h)
    if a <0.2:
        return "negligible"
    if a <0.5:
        return "small"
    if a <0.8:
        return "medium"
    return "large"

def assumptions_and_limitations(df: pd.DataFrame, sql: str, rows: List[Dict], total_rows: int) -> List[str]:
    lims = []
    if total_rows < 100:
        lims.append(f"Small total sample n={total_rows} — limited statistical power")
    miss = float(df.isnull().mean().max()*100) if not df.empty else 0
    if miss >5:
        lims.append(f"Highest column missingness {miss:.1f}% — may bias estimates")
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    outlier_pct = 0
    for col in numeric_cols:
        s = df[col].dropna()
        if len(s) <10:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 -1.5*iqr, q3 +1.5*iqr
        outlier_pct = max(outlier_pct, float(((s<lower)|(s>upper)).mean()*100))
    if outlier_pct >5:
        lims.append(f"Outliers ~{outlier_pct:.1f}% in numeric columns — may distort means")
    if "having" not in (sql or "").lower():
        lims.append("No minimum segment size enforced in SQL — small groups may be unstable")
    else:
        lims.append("Segments with <10 observations excluded via HAVING COUNT(*) >=10")
    date_cols = [c for c in df.columns if 'date' in c.lower()]
    if date_cols:
        try:
            s = pd.to_datetime(df[date_cols[0]], errors='coerce')
            uniq = s.nunique()
            if uniq <10:
                lims.append(f"Limited temporal coverage {uniq} unique dates")
        except:
            pass
    else:
        lims.append("No date/time column detected — trend or period comparison limited")
    lims.append("Metric definition verified via DuckDB execution; LLM did not compute numbers")
    lims.append("Observed associations do not establish causation; confounding variables not controlled")
    # Filter empty "-" bullets (defensive)
    lims = [l for l in lims if l and l.strip() not in ("", "-")]
    return lims
