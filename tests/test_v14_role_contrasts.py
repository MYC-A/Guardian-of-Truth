from scripts.v14_role_contrasts import component_splits,audit_row,NORMAL_QUOTE


def test_near_duplicate_component_cannot_straddle_reserved_tool_split():
    rows=[dict(source_tool='check_wifi_status',split_component='shared'),
          dict(source_tool='check_sim_status',split_component='shared'),
          dict(source_tool='check_vpn_status',split_component='other')]
    result=component_splits(rows)
    assert [r['proposed_split'] for r in result]==['holdout','holdout','train']
    assert 'proposed_split' not in rows[0]
