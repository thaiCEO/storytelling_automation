from app.utils.cost import estimate


def test_hook_cost_is_optional():
    base = estimate(1, "gpt-image-2", hook_enabled=False)
    with_hook = estimate(1, "gpt-image-2", hook_enabled=True)

    assert base["breakdown"]["hook"] == 0
    assert with_hook["breakdown"]["hook"] > 0
    assert with_hook["total"] > base["total"]


def test_flux_schnell_estimate_is_supported():
    result = estimate(1, "flux-schnell", hook_enabled=False)

    assert result["scenes"] == 10
    assert result["breakdown"]["images"] == 0.38


def test_grok_imagine_estimate_is_supported():
    result = estimate(1, "grok-imagine", hook_enabled=False)

    assert result["scenes"] == 10
    assert result["breakdown"]["images"] == 0.22
