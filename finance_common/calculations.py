"""Deterministic, intentionally simplified corporate finance calculations."""
import json
from pathlib import Path

CASE = Path(__file__).resolve().parents[1] / 'examples/finance/case.json'


def get_finance_case() -> dict:
    """Get the fictional acquisition case, all assumptions, and missing evidence."""
    return json.loads(CASE.read_text())


def analyze_finance_case(scenario: str = 'base') -> dict:
    """Compute auditable five-year DCF, debt stress, and simplified LBO returns.

    Only uses the supplied synthetic case. Returns assumptions, schedules, formulas,
    threshold tests, and model limitations. Supports base and downside scenarios.
    """
    case = get_finance_case()
    if scenario not in case['assumptions']:
        return {'error': 'Scenario must be base or downside'}
    a, tx, hist = case['assumptions'][scenario], case['transaction'], case['historical'][-1]
    if a['wacc'] <= a['terminal_growth']:
        return {'error': 'WACC must exceed terminal growth'}
    revenue, wc, debt = hist['revenue'], hist['working_capital'], tx['new_debt']
    rows = []
    for year in range(1, case['constraints']['horizon_years'] + 1):
        revenue *= 1 + a['revenue_growth']
        ebitda = revenue * a['ebitda_margin']
        da, capex, new_wc = revenue * a['depreciation_pct'], revenue * a['capex_pct'], revenue * a['working_capital_pct']
        delta_wc = new_wc - wc
        ufcf = (ebitda - da) * (1 - a['tax_rate']) + da - capex - delta_wc
        interest = debt * a['interest_rate']
        equity_cash = ufcf - interest * (1 - a['tax_rate'])
        debt_service = interest + min(tx['mandatory_annual_amortization'], debt)
        dscr = ufcf / debt_service if debt_service else None
        repayment = min(debt, max(0.0, equity_cash))
        unmet_amortization = max(0.0, min(tx['mandatory_annual_amortization'], debt) - repayment)
        debt -= repayment
        rows.append({'year': hist['year'] + year, 'revenue': revenue, 'ebitda': ebitda,
                     'unlevered_fcf': ufcf, 'interest': interest, 'debt_repayment': repayment,
                     'ending_debt': debt, 'dscr': dscr, 'cash_deficit': max(0.0, -equity_cash),
                     'unmet_mandatory_amortization': unmet_amortization,
                     'discounted_fcf': ufcf / (1 + a['wacc']) ** year})
        wc = new_wc
    horizon = len(rows)
    terminal = rows[-1]['unlevered_fcf'] * (1 + a['terminal_growth']) / (a['wacc'] - a['terminal_growth'])
    ev = sum(r['discounted_fcf'] for r in rows) + terminal / (1 + a['wacc']) ** horizon
    initial_equity = tx['enterprise_value'] + tx['fees'] - tx['new_debt']
    exit_equity = max(0.0, rows[-1]['ebitda'] * tx['exit_ebitda_multiple'] - debt)
    moic = exit_equity / initial_equity
    irr = moic ** (1 / horizon) - 1
    leverage = tx['new_debt'] / hist['ebitda']
    worst_dscr = min(r['dscr'] for r in rows if r['dscr'] is not None)
    maximum_by_leverage = hist['ebitda'] * case['constraints']['max_debt_to_ebitda']
    return {'synthetic': True, 'scenario': scenario, 'currency': case['currency'], 'units': case['units'],
            'assumptions': a, 'schedule': rows, 'dcf_enterprise_value': ev,
            'dcf_equity_value': ev - tx['existing_debt'] + tx['cash'], 'initial_sponsor_equity': initial_equity,
            'exit_sponsor_equity': exit_equity, 'sponsor_moic': moic, 'sponsor_annualized_return': irr,
            'entry_debt_to_ebitda': leverage, 'max_debt_by_leverage': maximum_by_leverage,
            'minimum_dscr': worst_dscr,
            'gates': {'leverage_pass': leverage <= case['constraints']['max_debt_to_ebitda'],
                      'dscr_pass': worst_dscr >= case['constraints']['min_dscr'],
                      'liquidity_pass': all(r['cash_deficit'] == 0 and r['unmet_mandatory_amortization'] == 0 for r in rows)},
            'formulas': {'ufcf': '(EBITDA - D&A)*(1-tax)+D&A-capex-change_in_working_capital',
                         'dscr': 'unlevered_fcf/(opening_debt*interest_rate+mandatory_amortization)',
                         'equity_cash': 'unlevered_fcf-interest*(1-tax)',
                         'dcf': 'sum(discounted_ufcf)+last_ufcf*(1+g)/(wacc-g)/(1+wacc)^years',
                         'return': '(exit_equity/initial_equity)^(1/years)-1'},
            'limitations': ['Illustrative operating model, not a linked three-statement workbook.',
                           'Excess cash sweeps debt; deficits and unmet amortization are flagged, not funded.',
                           'LBO assumes no interim distributions, flat exit multiple, no refinancing or transaction tax effects.',
                           'DSCR uses a simplified UFCF numerator; lender-specific definitions may differ.',
                           'No live prices, verified financial statements, ownership screening, or legal conclusions.']}
