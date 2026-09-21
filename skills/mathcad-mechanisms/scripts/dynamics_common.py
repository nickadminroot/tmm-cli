"""Repeated textbook constructions; no numerical answers substituted into XMCD."""
from book import Book


def steady_fluctuation(
    b: Book,
    *,
    minimum_guess,
    maximum_guess,
    controls: dict,
    phi_degrees,
    root_intervals: tuple[tuple[str, str], tuple[str, str]],
):
    """Mertsalov energy fluctuation approximation and exact two-extrema form.

    The extrema roots use four-argument ``root`` with explicit real intervals.
    Mathcad requires opposite endpoint signs, so each interval must bracket
    one zero rather than span a whole cycle with several crossings.
    A two-argument Newton search can leave the real kinematic branch even when
    the intended zero is real, which is especially easy to trigger near a
    mechanism's branch change.
    """
    b.text('Регулирование движения по методу Мерцалова',heading=True)
    b.D('T_II(φ)','I_прII(φ)*ω_cp**2/2')
    b.D('ΔT_I(φ)','A_Σ(φ)-T_II(φ)')
    b.plot(('φ/deg','T_II(φ)'), x_bounds=(0, phi_degrees),
           caption='Кинетическая энергия звеньев группы II при средней скорости')
    b.plot(('φ/deg','A_Σ(φ)'),('φ/deg','ΔT_I(φ)'), x_bounds=(0, phi_degrees),
           caption='Работа избыточного момента и изменение энергии группы I')
    b.text('Приближённое определение приведённого момента инерции группы I')
    b.D('t',minimum_guess); b.given(); b.D('t_min','Minimize(ΔT_I,t)')
    b.E('t_min/deg',controls['tmin']); b.E('ΔT_I(t_min)',controls['dmin'])
    b.D('t',maximum_guess); b.given(); b.D('t_max','Maximize(ΔT_I,t)')
    b.E('t_max/deg',controls['tmax']); b.E('ΔT_I(t_max)',controls['dmax'])
    b.D('ΔT_Iнб','ΔT_I(t_max)-ΔT_I(t_min)'); b.E('ΔT_Iнб',controls['range'])
    b.D('I_прI','ΔT_Iнб/(ω_cp**2*δ)'); b.E('I_прI',controls['iapprox'])
    b.D('Δω(φ)','(ΔT_I(φ)-(ΔT_I(t_max)+ΔT_I(t_min))/2)/(ω_cp*I_прI)')
    b.D('ω(φ)','ω_cp+Δω(φ)'); b.E('ω(0)',controls['w0approx'])
    b.text('Уточнение по положениям экстремальных скоростей')
    b.D('ω_max','ω_cp*(1+δ/2)'); b.D('ω_min','ω_cp*(1-δ/2)')
    b.E('ω_max',controls['wmax']); b.E('ω_min',controls['wmin'])
    (a_low, a_high), (b_low, b_high) = root_intervals
    b.D('φ_A',maximum_guess); b.D('u_1(x_A)','M_прΣ(x_A)-dI(x_A)*ω_max**2/2')
    b.D('Φ_A',f'root(u_1(x_A),x_A,{a_low},{a_high})'); b.E('Φ_A/deg',controls['pa'])
    b.D('φ_B',minimum_guess); b.D('u_2(x_B)','M_прΣ(x_B)-dI(x_B)*ω_min**2/2')
    b.D('Φ_B',f'root(u_2(x_B),x_B,{b_low},{b_high})'); b.E('Φ_B/deg',controls['pb'])


def steady_exact(b: Book, controls: dict, *, phi_degrees):
    b.D('I_прI','(2*(A_Σ(Φ_B)-A_Σ(Φ_A))+ω_max**2*I_прII(Φ_A)-ω_min**2*I_прII(Φ_B))/(ω_min**2-ω_max**2)')
    b.E('I_прI',controls['iexact'])
    b.D('I_прΣ(φ)','I_прI+I_прII(φ)')
    b.D('ω(φ)','sqrt((2*(A_Σ(φ)-A_Σ(Φ_A))+ω_max**2*I_прΣ(Φ_A))/I_прΣ(φ))')
    b.E('ω(0)',controls['w0exact'])
    b.plot(('φ/deg','ω(φ)'),('φ/deg','ω_cp'), x_bounds=(0, phi_degrees),
           caption='Угловая скорость начального звена и средняя скорость')


def angular_accelerations(b, members=(2,4)):
    b.D('ε_1(φ)','ω_q1*ε(φ)')
    for k in members: b.D(f'ε_{k}(φ)',f'ε_q{k}(φ)*ω(φ)**2+ω_q{k}(φ)*ε(φ)')


def accelerations(b, points):
    for point,axes in points:
        for ax in axes:
            b.D(f'a_{point}{ax}(φ)',f'a_q{point}{ax}(φ)*ω(φ)**2+V_q{point}{ax}(φ)*ε(φ)')


def vector_force(b, name, x, y, arg='φ'):
    b.D(f'{name}({arg})',f'sqrt({x}({arg})**2+{y}({arg})**2)')
    b.piece(f'φ_{name}({arg})',[(f'atan2({x}({arg})/{name}({arg}),{y}({arg})/{name}({arg}))',f'{name}({arg}) > 0')],default='0',
            why='Mathcad atan2 получает (x,y), а не порядок NumPy (y,x). При нулевой силе угол условно принят нулевым; физически он не определён.')
