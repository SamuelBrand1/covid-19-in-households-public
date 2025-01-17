''' Common utilities for transient bubble calculation.
'''
from numpy import (
    append, arange, around, array, atleast_2d, concatenate, copy,
    diag, hstack, isnan, ix_,
    ones, prod, shape, sum, unique, where, zeros, exp, log, repeat)
from numpy import int64 as my_int
from scipy.sparse import csc_matrix as sparse
from scipy.special import factorial
from scipy.stats import multinomial
from model.preprocessing import ModelInput, HouseholdPopulation, SEIRInput
from model.common import (
        build_state_matrix, build_external_import_matrix_SEPIRQ)
from model.imports import NoImportModel


def build_mixed_compositions_pairwise(
        composition_list, composition_distribution):

    no_comps = composition_list.shape[0]

    if composition_list.ndim == 1:
        hh_dimension = 1
    else:
        hh_dimension = composition_list.shape[1]

    mixed_comp_list = zeros((no_comps**2, 2*hh_dimension), dtype=my_int)
    mixed_comp_dist = zeros((no_comps**2, 1))

    pairings = [[], []]

    for hh1 in range(no_comps):
        for hh2 in range(no_comps):
            index = hh1*no_comps + hh2

            pairings[0].append(hh1)
            pairings[1].append(hh2)

            mixed_comp_list[index, :hh_dimension] = \
                composition_list[hh1,]
            mixed_comp_list[index,hh_dimension:] = \
                composition_list[hh2,]

            mixed_comp_dist[index] = \
             composition_distribution[hh1] * composition_distribution[hh2]

    return mixed_comp_list, mixed_comp_dist, hh_dimension, pairings

def build_mixed_compositions_threewise(composition_list,
                                        composition_distribution,
                                        max_size):

    no_comps = composition_list.shape[0]

    if composition_list.ndim==1:
        hh_dimension = 1
    else:
        hh_dimension = composition_list.shape[1]

    mixed_comp_list = []

    pairings = [[],[],[]]

    total_prob_1 = zeros((no_comps,))
    total_prob_2 = zeros((no_comps, no_comps)) # total_prob_2[i,j] stores summed probability of all possible third elements if first two are i,j

    for hh1 in range(no_comps):
        hh2_max = min(no_comps, int(0.5 * (max_size - (hh1+1))))
        total_prob_1[hh1] = sum(composition_distribution[:hh2_max])
        for hh2 in range(no_comps):
            hh3_max = min(no_comps, max_size - (hh1+1) - (hh2+1))
            total_prob_2[hh1, hh2] = sum(composition_distribution[:hh3_max])
            if (hh2>=hh1) and (hh2<hh2_max):
                for hh3 in range(hh2, hh3_max):

                    pairings[0].append(hh1)
                    pairings[1].append(hh2)
                    pairings[2].append(hh3)

                    this_merged_comp = zeros((3*hh_dimension,))
                    this_merged_comp[:hh_dimension] = \
                     composition_list[hh1,]
                    this_merged_comp[hh_dimension:2*hh_dimension] = \
                     composition_list[hh2,]
                    this_merged_comp[2*hh_dimension:] = \
                     composition_list[hh3,]

                    mixed_comp_list.append(this_merged_comp)

            #     total_prob_2[hh1, hh2] += composition_distribution[hh3]
            # total_prob_1[hh1] += composition_distribution[hh2]

    def mixed_comp_term(p0,p1,p2):
        hh2_max = min(no_comps, max_size - (p0 + 1) - 1)
        hh3_max = min(no_comps, max_size - (p0 + 1) - (p1 + 1))
        return composition_distribution[p0] * \
                    (composition_distribution[p1] /
                    sum(composition_distribution[:hh2_max])) * \
                    (composition_distribution[p2] /
                    sum(composition_distribution[:hh3_max]))

    no_merged_comps = len(mixed_comp_list)
    mixed_comp_list = array(mixed_comp_list, dtype=my_int)
    pairings = array(pairings, dtype=my_int).T
    mixed_comp_dist = zeros((no_merged_comps,))
    for mc in range(no_merged_comps):
        p_unique = unique(pairings[mc, :])
        if len(p_unique)==1:
            mixed_comp_dist[mc] = mixed_comp_term(p_unique[0],p_unique[0],p_unique[0])
        elif len(p_unique)==2:
            if len(where(pairings[mc,:]==p_unique[0])[0])==2:
                pair0 = p_unique[0]
                pair1 = p_unique[1]
            else:
                pair0 = p_unique[1]
                pair1 = p_unique[0]
            mixed_comp_dist[mc] = mixed_comp_term(pair0, pair0, pair1) + \
                                        mixed_comp_term(pair0, pair1, pair0) + \
                                        mixed_comp_term(pair1, pair0, pair0)
        else:
            pair0 = p_unique[0]
            pair1 = p_unique[1]
            pair2 = p_unique[2]
            mixed_comp_dist[mc] = mixed_comp_term(pair0,pair1,pair2) + \
                                    mixed_comp_term(pair0, pair2, pair1) + \
                                    mixed_comp_term(pair1, pair0, pair2) + \
                                    mixed_comp_term(pair1, pair2, pair0) + \
                                    mixed_comp_term(pair2, pair0, pair1) + \
                                    mixed_comp_term(pair2, pair1, pair0)
        # if len(unique(pairings[mc,:]))==2:
        #     mixed_comp_dist[mc] = 3 * mixed_comp_dist[mc]
        # elif len(unique(pairings[mc,:]))==3:
        #     mixed_comp_dist[mc] = 6 * mixed_comp_dist[mc]

    return mixed_comp_list, mixed_comp_dist, hh_dimension, pairings


def pairwise_merged_initial_condition(H_unmerged,
                            unmerged_population,
                            merged_population,
                            hh_dimension,
                            pairings,
                            no_compartments=5):
    H0_len = sum(merged_population.system_sizes)
    H0 = zeros((H0_len,))
    reverse_prod = unmerged_population.reverse_prod
    index_vector_list = unmerged_population.index_vector
    which_composition = merged_population.which_composition
    merged_states = merged_population.states

    for i in range(H0_len):
        comp_0 = pairings[0][which_composition[i]]
        comp_1 = pairings[1][which_composition[i]]
        state_0 = merged_states[i, :no_compartments]
        state_1 = merged_states[i, no_compartments:]
        index_vector_0 = index_vector_list[comp_0]
        index_vector_1 = index_vector_list[comp_1]
        index_0 = index_vector_0[
            state_0.dot(reverse_prod[comp_0]) + state_0[-1], 0]
        index_1 = index_vector_1[
            state_1.dot(reverse_prod[comp_1]) + state_1[-1], 0]
        H0[i] = H_unmerged[index_0] * H_unmerged[index_1]

    return H0


def initialise_merged_system_threewise(
        H0_unmerged,
        unmerged_population,
        merged_population,
        state_match):

    wc_um = unmerged_population.which_composition
    wc_m = merged_population.which_composition
    cd_um = unmerged_population.composition_distribution
    cd_m = merged_population.composition_distribution
    no_merged_states = len(wc_m)
    H0_merged = zeros((no_merged_states,))
    for state_no in range(no_merged_states):
        this_H0_merged = \
            cd_m[wc_m[state_no]] \
            * prod(H0_unmerged[state_match[state_no, :]]) \
            / prod(cd_um[wc_um[state_match[state_no, :]]])
        # for hh in range(3):
        #     this_H0_merged = this_H0_merged * \
        #                         H0_unmerged[state_match[state_no, hh]] / \
        #                         cd_um[wc_um[state_match[state_no, hh]]]
        H0_merged[state_no] = this_H0_merged

    return H0_merged


def pairwise_demerged_initial_condition(
        H_merged,
        unmerged_population,
        merged_population,
        hh_dimension,
        pairings,
        no_compartments=5):
    H0_len = sum(unmerged_population.system_sizes)
    H0 = zeros((H0_len,))
    reverse_prod = unmerged_population.reverse_prod
    index_vector_list = unmerged_population.index_vector
    which_composition = merged_population.which_composition
    merged_states = merged_population.states

    for i in range(len(H_merged)):
        comp_0 = pairings[0][which_composition[i]]
        comp_1 = pairings[1][which_composition[i]]
        state_0 = merged_states[i, :no_compartments]
        state_1 = merged_states[i, no_compartments:]
        index_vector_0 = index_vector_list[comp_0]
        index_vector_1 = index_vector_list[comp_1]
        index_0 = index_vector_0[
            state_0.dot(reverse_prod[comp_0]) + state_0[-1], 0]
        index_1 = index_vector_1[
            state_1.dot(reverse_prod[comp_1]) + state_1[-1], 0]
        H0[index_0] += 0.5*H_merged[i]
        H0[index_1] += 0.5*H_merged[i]

    return H0


def build_mixed_compositions(
        composition_list,
        composition_distribution,
        no_hh=2,
        max_size=12):

    no_comps = composition_list.shape[0]

    if composition_list.ndim == 1:
        hh_dimension = 1
    else:
        hh_dimension = composition_list.shape[1]

    no_mixed_comps = 0

    mixed_comp_list = []
    mixed_comp_dist = []

    hhi = no_hh*[0]
    pairings = []
    for pairing_index in range(no_hh):
        pairings.append([])
    coeff = [] # This stores number of appearances each combination would make in a "full" merged list

    def comp_iterator(depth, no_hh):
        if depth < no_hh:
            for i in range(hhi[depth-1], no_comps):
                hhi[depth] = i
                comp_iterator(depth+1, no_hh)
        else:
            index = 0
            for hh in range(no_hh):
                index +=  hhi[hh] * no_comps**(no_hh - 1 - hh)
                pairings[hh].append(hhi[hh])
            this_mix_comp = zeros((no_hh*hh_dimension,))
            hist = zeros((no_comps,))
            for hh in range(no_hh):
                this_mix_comp[hh*hh_dimension:(hh+1)*hh_dimension] = \
                 composition_list[hhi[hh], ]  # TODO: What happens after the comma?
                hist[hhi[hh]] += 1
            this_mix_prob = multinomial.pmf(
                hist, n=no_hh, p=composition_distribution)
            mixed_comp_list.append(this_mix_comp)
            mixed_comp_dist.append(this_mix_prob)
            coeff.append(factorial(no_hh)/prod(factorial(hist)))

    comp_iterator(0, no_hh)
    mixed_comp_list = array(mixed_comp_list, dtype=my_int)
    mixed_comp_dist = array(mixed_comp_dist)
    coeff = array(coeff)
    pairings = array(pairings).T
    print(
        'Before checking for big households, sum(dist)=',
        sum(mixed_comp_dist))

    reverse_prod = hstack(([0], no_comps**arange(1, no_hh)))
    no_mixed_comps = len(mixed_comp_dist)
    rows = [
        mixed_comp_list[k, :].dot(reverse_prod) + mixed_comp_list[k, 0]
        for k in range(no_mixed_comps)]
    mixed_comp_index_vector = sparse((
        arange(no_mixed_comps),
        (rows, [0]*no_mixed_comps)), dtype=my_int)

    mixed_sizes = mixed_comp_list.sum(axis=1)
    large_merges = where(mixed_sizes > max_size)[0]

    ref_dist = deepcopy(mixed_comp_dist)

    for merge_no in large_merges:
        this_prob = mixed_comp_dist[merge_no]
        this_comp = mixed_comp_list[merge_no, :]
        current_size = mixed_sizes[merge_no]
        while current_size > max_size:
            this_comp[this_comp.argmax()] -= 1
            current_size -= 1
        new_comp_loc = mixed_comp_index_vector[
            this_comp.dot(reverse_prod) + this_comp[0], 0]
        mixed_comp_dist[new_comp_loc] += this_prob

    print(
        'After checking for big households, sum(dist)=',
        sum(mixed_comp_dist))
    # Stores level of inflation of probability caused by adding prob of
    # compositions with size>max to ones with size<=max
    comp_scaler = mixed_comp_dist / ref_dist

    print(large_merges)
    print('Before deletion mixed_comp_list.shape=', mixed_comp_list.shape)
    mixed_comp_list = delete(mixed_comp_list, large_merges, axis=0)
    print('After deletion mixed_comp_list.shape=', mixed_comp_list.shape)
    print('Before deletion mixed_comp_dist.shape=', mixed_comp_dist.shape)
    mixed_comp_dist = delete(mixed_comp_dist, large_merges, axis=0)
    print('After deletion mixed_comp_dist.shape=', mixed_comp_dist.shape)
    print('Before deletion coeff.shape=', coeff.shape)
    coeff = delete(coeff, large_merges, axis=0)
    print('After deletion coeff.shape=', coeff.shape)
    print('Before deletion pairings.shape=', pairings.shape)
    pairings = delete(pairings, large_merges, axis=0)
    print('After deletion pairings.shape=', pairings.shape)
    print('Before deletion comp_scaler.shape=', comp_scaler.shape)
    comp_scaler = delete(comp_scaler, large_merges, axis=0)
    print('After deletion comp_scaler.shape=', comp_scaler.shape)

    return \
        mixed_comp_list, \
        mixed_comp_dist, \
        hh_dimension, \
        pairings, \
        mixed_comp_index_vector, \
        reverse_prod, \
        coeff, \
        comp_scaler


def match_merged_states_to_unmerged(
        unmerged_population,
        merged_population,
        pairings,
        no_hh,
        no_compartments):

    rp_um = unmerged_population.reverse_prod
    iv_um = unmerged_population.index_vector
    states_m = merged_population.states
    wc_m = merged_population.which_composition

    # pdb.set_trace()
    # iv_shifter = hstack((array(0),cumsum(unmerged_population.system_sizes))) # This shifts the index vectors so that they give you indices in the  full state list rather than in the individual matrix blocks

    state_match = zeros((len(wc_m), no_hh), dtype=my_int)

    for state_no in range(len(wc_m)):
        merged_comp = wc_m[state_no]
        for hh in range(no_hh):
            unmerged_comp = pairings[merged_comp, hh]
            this_iv = iv_um[unmerged_comp]
            this_state = states_m[
                state_no, hh * no_compartments:(hh+1) * no_compartments]
            index = this_iv[
                this_state.dot(rp_um[unmerged_comp]) + this_state[-1], 0]
            state_match[state_no, hh] = index

    return state_match

def initialise_merged_system(H0_unmerged,
                            merged_population,
                            state_match,
                            coeff,
                            comp_scaler,
                            no_hh):

    wc_m = merged_population.which_composition
    no_merged_states = len(wc_m)
    H0_merged = zeros((no_merged_states,))
    for state_no in range(no_merged_states):
        log_H0_merged = 0
        for hh in range(no_hh):
            # print(hh)
            # print(state_no)
            # print(state_match[state_no, hh])
            log_H0_merged += log(H0_unmerged[state_match[state_no, hh]])
        H0_merged[state_no] = coeff[wc_m[state_no]] * \
                              comp_scaler[wc_m[state_no]] * \
                              exp(log_H0_merged)

    return H0_merged



def my_multinomial(hist, n, p):
    log_prob = sum(log(arange(1, n+1)))
    for i in range(len(hist)):
        log_prob += hist[i] * log(p[i]) - sum(log(arange(1, hist[i]+1)))
    return exp(log_prob)


def merged_initial_condition(
        H_unmerged,
        unmerged_population,
        merged_population,
        hh_dimension,
        pairings,
        no_hh=2,
        no_compartments=5):
    H0_len = sum(merged_population.system_sizes)
    H0 = ones((H0_len,))
    reverse_prod = unmerged_population.reverse_prod
    index_vector_list = unmerged_population.index_vector
    which_composition = merged_population.which_composition
    merged_states = merged_population.states

    for i in range(H0_len):
        hist = zeros(len(H_unmerged,))
        for hh in range(no_hh):
            comp = pairings[hh][which_composition[i]]
            state = merged_states[
                i,
                hh * hh_dimension * no_compartments:
                (hh+1) * hh_dimension * no_compartments]
            index_vector = index_vector_list[comp]
            index = index_vector[
                state.dot(reverse_prod[comp]) + state[-1], 0]
            hist[index] += 1
        H0[i] = multinomial.pmf(hist, n=no_hh, p=H_unmerged)
    return H0


def merged_initial_condition_alt(
        H_unmerged,
        unmerged_population,
        merged_population,
        hh_dimension,
        mixed_comp_index_vector,
        mixed_comp_reverse_prod,
        pairings,
        no_hh=2,
        no_compartments=5):
    no_unmerged_states = sum(unmerged_population.system_sizes)
    H0_len = sum(merged_population.system_sizes)
    H0 = zeros((H0_len,))
    unmerged_reverse_prod = unmerged_population.reverse_prod
    merged_reverse_prod = merged_population.reverse_prod
    index_vector_list = merged_population.index_vector
    which_composition = merged_population.which_composition
    merged_states = merged_population.states
    unmerged_states = unmerged_population.states

    hhi = zeros((no_hh,), dtype=my_int)
    unmerged_comps = zeros((no_hh,))

    this_merged_state = zeros((no_hh * no_compartments))
    def state_iterator(depth, no_hh):
        if depth<no_hh:
            for i in range(hhi[depth-1],no_unmerged_states):
                hhi[depth] = i
                unmerged_comps[depth] = unmerged_population.composition_list[unmerged_population.which_composition[i]]
                this_merged_state[
                    depth * no_compartments:(depth+1) * no_compartments] = unmerged_states[i,:]
                state_iterator(depth+1, no_hh)
        else:
            if unmerged_comps.dot(mixed_comp_reverse_prod) + unmerged_comps[0] in mixed_comp_index_vector.indices:
                merged_comp = mixed_comp_index_vector[
                    unmerged_comps.dot(mixed_comp_reverse_prod) + unmerged_comps[0], 0]
                index_vector = index_vector_list[merged_comp]
                reverse_prod = merged_reverse_prod[merged_comp]
                index = index_vector[
                    this_merged_state.dot(reverse_prod) + this_merged_state[-1], 0]
                hist = zeros((no_unmerged_states,))
                for hh in range(no_hh):
                    hist[hhi[hh]] += 1
                H0[index] += multinomial.pmf(hist, n=no_hh, p=H_unmerged)

    state_iterator(0,no_hh)

    return H0

def demerged_initial_condition(H_merged,
                            unmerged_population,
                            merged_population,
                            hh_dimension,
                            pairings,
                            no_hh =2,
                            no_compartments = 5):
    H0_len = sum(unmerged_population.system_sizes)
    H0 = zeros((H0_len,))
    reverse_prod = unmerged_population.reverse_prod
    index_vector_list = unmerged_population.index_vector
    which_composition = merged_population.which_composition
    merged_states = merged_population.states
    unmerged_states = unmerged_population.states

    for i in range(len(H_merged)):
        for hh in range(no_hh):
            comp = pairings[which_composition[i], hh]
            state = merged_states[i,
                hh * hh_dimension * no_compartments :
                (hh+1) * hh_dimension * no_compartments]
            index_vector = index_vector_list[comp]
            index = index_vector[
                state.dot(reverse_prod[comp]) + state[-1], 0]
            H0[index] += (1 / no_hh) * H_merged[i]

    return H0

SINGLE_AGE_CLASS_SPEC = {
    # Interpretable parameters:
    'R_int': 1.01,                      # Within-household reproduction ratio
    'recovery_rate': 1/4,           # Recovery rate
    'incubation_rate': 1/1,         # E->P incubation rate
    'symp_onset_rate': 1/4,         # P->I prodromal to symptomatic rate
    'prodromal_trans_scaling':
     array([0.5]),          # Prodromal transmission intensity relative to full inf transmission
    'sus': array([1]),          # Relative susceptibility by age/vulnerability class
    'external_trans_scaling': 1.5 * 1/24,  # Relative intensity of external compared to internal contacts
    # We don't actually use these two mixing matrices, but we need them to make the abstract base class work
    'k_home': {
        'file_name': 'inputs/MUestimates_home_2.xlsx',
        'sheet_name':'United Kingdom of Great Britain'
    },
    'k_all': {
        'file_name': 'inputs/MUestimates_all_locations_2.xlsx',
        'sheet_name': 'United Kingdom of Great Britain'
    }
}

SINGLE_AGE_CLASS_SEIR_SPEC = {
    # Interpretable parameters:
    'R_int': 1.2,                      # Within-household reproduction ratio
    'recovery_rate': 1/8,           # Recovery rate
    'incubation_rate': 1/1,         # E->P incubation rate
    'sus': array([1]),          # Relative susceptibility by age/vulnerability class
    'external_trans_scaling': 1.5 * 1/24,  # Relative intensity of external compared to internal contacts
    'density_exponent': 1,
    # We don't actually use these two mixing matrices, but we need them to make the abstract base class work
    'k_home': {
        'file_name': 'inputs/MUestimates_home_2.xlsx',
        'sheet_name':'United Kingdom of Great Britain'
    },
    'k_all': {
        'file_name': 'inputs/MUestimates_all_locations_2.xlsx',
        'sheet_name': 'United Kingdom of Great Britain'
    }
}

class DataObject():
    def __init__(self,thing):
        self.thing = thing

class SingleClassInput(ModelInput):
    '''TODO: add docstring'''
    def __init__(self, spec):
        super().__init__(spec)

        self.k_home = array(spec['R_int'], ndmin=2)
        self.k_ext = array(
            spec['R_int'] * spec['external_trans_scaling'], ndmin=2)
        self.tau = spec['prodromal_trans_scaling']
        self.sus = spec['sus']
        self.import_model = NoImportModel()

    @property
    def alpha_1(self):
        return self.spec['incubation_rate']

    @property
    def alpha_2(self):
        return self.spec['symp_onset_rate']

    @property
    def gamma(self):
        return self.spec['recovery_rate']

class SingleClassSEIRInput(ModelInput):
    '''TODO: add docstring'''
    def __init__(self, spec):
        super().__init__(spec)

        self.k_home = array(
            spec['R_int'] *
            spec['recovery_rate'] *
            (1 - spec['external_trans_scaling']),
            ndmin=2)

        self.k_ext = array(
            spec['R_int'] *
            spec['recovery_rate'] *
            spec['external_trans_scaling'],
            ndmin=2)
        self.sus = spec['sus']
        self.import_model = NoImportModel()
        self.density_expo = spec['density_exponent']

    @property
    def alpha_1(self):
        return self.spec['incubation_rate']

    @property
    def gamma(self):
        return self.spec['recovery_rate']

class MergedInput(ModelInput):
    '''TODO: add docstring'''
    def __init__(self, spec, no_hh, guest_trans_scaling):
        super().__init__(spec)
        self.k_home = \
            diag((1-guest_trans_scaling) * spec['R_int'] * ones((no_hh,))) + \
                    guest_trans_scaling * spec['R_int'] * ones((no_hh,no_hh))
        self.k_ext = \
         spec['R_int'] * spec['external_trans_scaling'] * ones((no_hh,no_hh))
        self.tau = spec['prodromal_trans_scaling'] * ones((no_hh,))
        self.sus = spec['sus'] * ones((no_hh,))
        self.import_model = NoImportModel()

    @property
    def alpha_1(self):
        return self.spec['incubation_rate']

    @property
    def alpha_2(self):
        return self.spec['symp_onset_rate']

    @property
    def gamma(self):
        return self.spec['recovery_rate']

class MergedSEIRInput(SEIRInput):
    '''This creates the model input for an SEIR compartmental structured '''
    '''merged household model.'''
    def __init__(self, spec, comp_list, comp_dist, no_hh, guest_trans_scaling):
        super().__init__(spec, comp_list, comp_dist)

        self.k_home = \
            diag((1-guest_trans_scaling) * self.k_home * ones((no_hh,))) + \
                    guest_trans_scaling * self.k_home * ones((no_hh,no_hh))
        self.k_ext = self.k_ext * ones((no_hh,no_hh))
        self.sus = repeat(self.sus, no_hh)
        for i in range(len(self.inf_scales)):
            self.inf_scales[i] = repeat(self.inf_scales[i], no_hh)


def make_initial_condition(
        household_population,
        rhs,
        prev=1.0e-5):
    '''TODO: docstring'''
    fully_sus = where(
        rhs.states_sus_only.sum(axis=1)
        ==
        household_population.states.sum(axis=1))[0]
    print(len(fully_sus))
    i_is_one = where(
        (rhs.states_inf_only).sum(axis=1) == 1)[0]
    print(len(i_is_one))
    H0 = zeros(len(household_population.which_composition))
    x = household_population.composition_distribution[
            household_population.which_composition[i_is_one]]
    H0[i_is_one] = prev * x
    H0[fully_sus] = (1.0 - prev * sum(x)) \
            * household_population.composition_distribution
    return H0


def make_initial_condition_with_recovereds(
        household_population,
        rhs,
        prev=1.0e-2,
        seroprev=5.6e-2,
        AR=1.0):
    '''TODO: docstring'''
    fully_sus = where(
        rhs.states_sus_only.sum(axis=1)
        ==
        household_population.states.sum(axis=1))[0]
    already_visited = where(
        (rhs.states_rec_only.sum(axis=1)
            == around(AR*household_population.states.sum(axis=1)).astype(int)
            & ((rhs.states_sus_only + rhs.states_rec_only).sum(axis=1)
                == household_population.states.sum(axis=1)))
        & ((rhs.states_rec_only).sum(axis=1) > 0))[0]
    # This last condition is needed to make sure we don't include any fully
    # susceptible states
    i_is_one = where(
        ((rhs.states_inf_only).sum(axis=1) == 1)
        & ((
            rhs.states_sus_only+rhs.states_inf_only).sum(axis=1)
            ==
            household_population.states.sum(axis=1))
    )[0]
    ave_hh_size = sum(
        household_population.composition_distribution.T.dot(
            household_population.composition_list))
    H0 = zeros(len(household_population.which_composition))
    inf_comps = household_population.which_composition[i_is_one]
    x = array([])
    for state in i_is_one:
        x = append(
            x,
            (1/len(inf_comps == household_population.which_composition[state]))
            * household_population.composition_distribution[
                household_population.which_composition[state]])
        # base_comp_dist[household_population.which_composition[state]]-=x[-1]
    visited_comps = household_population.which_composition[already_visited]
    y = array([])
    for state in already_visited:
        y = append(
            y,
            (1/len(
                visited_comps
                == household_population.which_composition[state]))
            * household_population.composition_distribution[
                household_population.which_composition[state]])
        # base_comp_dist[household_population.which_composition[state]]-=y[-1]
    # y = household_population.composition_distribution[
    #     household_population.which_composition[already_visited]]
    H0[i_is_one] = ave_hh_size*(prev/sum(x)) * x
    H0[already_visited] = ave_hh_size*((seroprev/AR)/sum(y)) * y
    H0[fully_sus] = (1-sum(H0)) * household_population.composition_distribution

    return H0

class IndexedHousePopulation(HouseholdPopulation):
    def __init__(
            self,
            composition_list,
            composition_distribution,
            model_input,
            no_compartments,
            print_progress=True):
        super().__init__(
            composition_list,
            composition_distribution,
            model_input,
            no_compartments,
            print_progress=print_progress)

    def _assemble_system(self, household_subsystem_specs, model_parts):
        super()._assemble_system(
            household_subsystem_specs,
            model_parts)
        self.reverse_prod = [part[5] for part in model_parts]
        for i, parts in enumerate(model_parts):
            model_parts[i][6].data += self.offsets[i]
        self.index_vector = [part[6] for part in model_parts]


class SEPIRHouseholdPopulation(IndexedHousePopulation):
    def __init__(
            self,
            composition_list,
            composition_distribution,
            model_input,
            print_progress=True):
        super().__init__(
            composition_list,
            composition_distribution,
            model_input,
            no_compartments=5,
            print_progress=print_progress)

    def _create_subsystems(self, household_spec):
        '''Assuming frequency-dependent homogeneous within-household mixing
        composition[i] is the number of individuals in age-class i inside the
        household'''

        composition = household_spec.composition
        sus = self.model_input.sus
        tau = self.model_input.tau
        K_home = self.model_input.k_home
        alpha_1 = self.model_input.alpha_1
        alpha_2 = self.model_input.alpha_2
        gamma = self.model_input.gamma

        no_compartments = self.num_of_epidemiological_compartments

        # Set of individuals actually present here
        # classes_present = where(composition.ravel() > 0)[0]
        classes_idx = household_spec.class_indexes
        K_home = K_home[ix_(classes_idx, classes_idx)]
        sus = sus[classes_idx]
        tau = tau[classes_idx]
        r_home = atleast_2d(diag(sus).dot(K_home))

        states, \
            reverse_prod, \
            index_vector, \
            rows = build_state_matrix(household_spec)

        p_pos = 2 + no_compartments * arange(len(classes_idx))
        i_pos = 3 + no_compartments * arange(len(classes_idx))

        Q_int = sparse(household_spec.matrix_shape)
        inf_event_row = array([], dtype=my_int)
        inf_event_col = array([], dtype=my_int)
        inf_event_class = array([], dtype=my_int)

        # Add events for each age class
        for i in range(len(classes_idx)):
            s_present = where(states[:, no_compartments*i] > 0)[0]
            e_present = where(states[:, no_compartments*i+1] > 0)[0]
            p_present = where(states[:, no_compartments*i+2] > 0)[0]
            i_present = where(states[:, no_compartments*i+3] > 0)[0]

            # First do infection events
            inf_to = zeros(len(s_present), dtype=my_int)
            inf_rate = zeros(len(s_present))
            for k in range(len(s_present)):
                old_state = copy(states[s_present[k], :])
                # tau is prodromal reduction
                inf_rate[k] = old_state[no_compartments*i] * (
                    r_home[i, :].dot(
                        (old_state[i_pos] / composition[classes_idx])
                        + tau * (
                            old_state[p_pos] /
                            composition[classes_idx])))
                new_state = old_state.copy()
                new_state[no_compartments*i] -= 1
                new_state[no_compartments*i + 1] += 1
                inf_to[k] = index_vector[
                    new_state.dot(reverse_prod) + new_state[-1], 0]
            Q_int += sparse(
                (inf_rate, (s_present, inf_to)),
                shape=household_spec.matrix_shape)
            inf_event_row = concatenate((inf_event_row, s_present))
            inf_event_col = concatenate((inf_event_col, inf_to))
            inf_event_class = concatenate(
                (inf_event_class, classes_idx[i]*ones((len(s_present)))))
            # input('Press enter to continue')
            # # disp('Infection events done')
            # # Now do exposure to prodromal
            inc_to = zeros(len(e_present), dtype=my_int)
            inc_rate = zeros(len(e_present))
            for k in range(len(e_present)):
                # First do detected
                old_state = copy(states[e_present[k], :])
                inc_rate[k] = alpha_1 * old_state[no_compartments*i+1]
                new_state = copy(old_state)
                new_state[no_compartments*i + 1] -= 1
                new_state[no_compartments*i + 2] += 1
                inc_to[k] = index_vector[
                    new_state.dot(reverse_prod) + new_state[-1], 0]

            Q_int += sparse(
                (inc_rate, (e_present, inc_to)),
                shape=household_spec.matrix_shape)
            # # disp('Incubaion events done')
            # # Now do prodromal to infectious
            dev_to = zeros(len(p_present), dtype=my_int)
            dev_rate = zeros(len(p_present))
            for k in range(len(p_present)):
                # First do detected
                old_state = copy(states[p_present[k], :])
                dev_rate[k] = alpha_2 * old_state[no_compartments*i+2]
                new_state = copy(old_state)
                new_state[no_compartments*i + 2] -= 1
                new_state[no_compartments*i + 3] += 1
                dev_to[k] = index_vector[
                    new_state.dot(reverse_prod) + new_state[-1], 0]

            Q_int += sparse(
                (dev_rate, (p_present, dev_to)),
                shape=household_spec.matrix_shape)

            # Now do recovery of detected cases
            rec_to = zeros(len(i_present), dtype=my_int)
            rec_rate = zeros(len(i_present))
            for k in range(len(i_present)):
                old_state = copy(states[i_present[k], :])
                rec_rate[k] = gamma * old_state[no_compartments*i+3]
                new_state = copy(old_state)
                new_state[no_compartments*i+3] -= 1
                new_state[no_compartments*i+4] += 1
                rec_to[k] = index_vector[
                    new_state.dot(reverse_prod) + new_state[-1], 0]
            Q_int += sparse(
                (rec_rate, (i_present, rec_to)),
                shape=household_spec.matrix_shape)

        S = Q_int.sum(axis=1).getA().squeeze()
        Q_int += sparse((
            -S,
            (
                arange(household_spec.total_size),
                arange(household_spec.total_size)
            )))
        return tuple((
            Q_int,
            states,
            array(inf_event_row, dtype=my_int, ndmin=1),
            array(inf_event_col, dtype=my_int, ndmin=1),
            array(inf_event_class, dtype=my_int, ndmin=1),
            reverse_prod,
            index_vector))


class SEIRHouseholdPopulation(IndexedHousePopulation):
    def __init__(
            self,
            composition_list,
            composition_distribution,
            model_input,
            print_progress=True):

        super().__init__(
            composition_list,
            composition_distribution,
            model_input,
            no_compartments=4,
            print_progress=print_progress)

    def _create_subsystems(self, household_spec):
        '''Assuming frequency-dependent homogeneous within-household mixing
        composition[i] is the number of individuals in age-class i inside the
        household'''

        sus = self.model_input.sus
        K_home = self.model_input.k_home
        alpha_1 = self.model_input.alpha_1
        gamma = self.model_input.gamma
        density_expo = self.model_input.density_expo

        no_compartments = self.num_of_epidemiological_compartments

        # Set of individuals actually present here
        classes_idx = household_spec.class_indexes
        K_home = K_home[ix_(classes_idx, classes_idx)]
        sus = sus[classes_idx]
        r_home = atleast_2d(diag(sus).dot(K_home))

        states, \
            reverse_prod, \
            index_vector, \
            rows = build_state_matrix(household_spec)

        i_pos = 2 + no_compartments * arange(len(classes_idx))

        Q_int = sparse(household_spec.matrix_shape)
        inf_event_row = array([], dtype=my_int)
        inf_event_col = array([], dtype=my_int)
        inf_event_class = array([], dtype=my_int)

        # Add events for each age class
        for i in range(len(classes_idx)):
            s_present = where(states[:, no_compartments*i] > 0)[0]
            e_present = where(states[:, no_compartments*i+1] > 0)[0]
            i_present = where(states[:, no_compartments*i+2] > 0)[0]

            # First do infection events
            inf_to = zeros(len(s_present), dtype=my_int)
            inf_rate = zeros(len(s_present))
            for k in range(len(s_present)):
                old_state = copy(states[s_present[k], :])
                # tau is prodromal reduction
                inf_rate[k] = old_state[no_compartments*i] * (
                    r_home[i, :].dot(
                        old_state[i_pos]
                        / household_spec.composition[classes_idx]**density_expo))
                new_state = old_state.copy()
                new_state[no_compartments*i] -= 1
                new_state[no_compartments*i + 1] += 1
                inf_to[k] = index_vector[
                    new_state.dot(reverse_prod) + new_state[-1], 0]
            Q_int += sparse(
                (inf_rate, (s_present, inf_to)),
                shape=household_spec.matrix_shape)
            inf_event_row = concatenate((inf_event_row, s_present))
            inf_event_col = concatenate((inf_event_col, inf_to))
            inf_event_class = concatenate(
                (inf_event_class, classes_idx[i]*ones((len(s_present)))))
            # input('Press enter to continue')
            # # disp('Infection events done')
            # # Now do exposure to prodromal
            inc_to = zeros(len(e_present), dtype=my_int)
            inc_rate = zeros(len(e_present))
            for k in range(len(e_present)):
                # First do detected
                old_state = copy(states[e_present[k], :])
                inc_rate[k] = alpha_1 * old_state[no_compartments*i+1]
                new_state = copy(old_state)
                new_state[no_compartments*i + 1] -= 1
                new_state[no_compartments*i + 2] += 1
                inc_to[k] = index_vector[
                    new_state.dot(reverse_prod) + new_state[-1], 0]
            Q_int += sparse(
                (inc_rate, (e_present, inc_to)),
                shape=household_spec.matrix_shape)

            # Now do recovery of detected cases
            rec_to = zeros(len(i_present), dtype=my_int)
            rec_rate = zeros(len(i_present))
            for k in range(len(i_present)):
                old_state = copy(states[i_present[k], :])
                rec_rate[k] = gamma * old_state[no_compartments*i+2]
                new_state = copy(old_state)
                new_state[no_compartments*i+2] -= 1
                new_state[no_compartments*i+3] += 1
                rec_to[k] = index_vector[
                    new_state.dot(reverse_prod) + new_state[-1], 0]
            Q_int += sparse(
                (rec_rate, (i_present, rec_to)),
                shape=household_spec.matrix_shape)
            # disp('Recovery events from detecteds done')

        S = Q_int.sum(axis=1).getA().squeeze()
        Q_int += sparse((
            -S,
            (
                arange(household_spec.total_size),
                arange(household_spec.total_size)
            )))
        return tuple((
            Q_int,
            states,
            array(inf_event_row, dtype=my_int, ndmin=1),
            array(inf_event_col, dtype=my_int, ndmin=1),
            array(inf_event_class, dtype=my_int, ndmin=1),
            reverse_prod,
            index_vector))


class RateEquations:
    '''This class represents a functor for evaluating the rate equations for
    the model with no imports of infection from outside the population. The
    state of the class contains all essential variables'''
    # pylint: disable=invalid-name
    def __init__(self,
                 model_input,
                 household_population,
                 epsilon=1.0,        # TODO: this needs a better name
                 no_compartments=5
                 ):

        self.household_population = household_population
        self.epsilon = epsilon
        self.Q_int = household_population.Q_int
        # To define external mixing we need to set up the transmission
        # matrices.
        # Scale rows of contact matrix by
        self.inf_trans_matrix = diag(model_input.sus).dot(model_input.k_ext)
        # age-specific susceptibilities
        # Scale columns by asymptomatic reduction in transmission
        self.pro_trans_matrix = diag(model_input.sus).dot(
            model_input.k_ext.dot(diag(model_input.tau)))
        # This stores number in each age class by household
        self.composition_by_state = household_population.composition_by_state
        # ::5 gives columns corresponding to susceptible cases in each age
        # class in each state
        self.states_sus_only = household_population.states[:, ::no_compartments]

        self.s_present = where(self.states_sus_only.sum(axis=1) > 0)[0]
        # 2::5 gives columns corresponding to detected cases in each age class
        # in each state
        self.states_pro_only = household_population.states[:, 2::no_compartments]
        # 4:5:end gives columns corresponding to undetected cases in each age
        # class in each state
        self.states_inf_only = household_population.states[:, 3::no_compartments]
        self.states_rec_only = household_population.states[:, 4::no_compartments]
        self.epsilon = epsilon
        self.import_model = model_input.import_model

    def __call__(self, t, H):
        '''hh_ODE_rates calculates the rates of the ODE system describing the
        household ODE model'''
        Q_ext_pro, Q_ext_inf = self.external_matrices(t, H)
        if (H < 0).any():
            H[where(H < 0)[0]] = 0
        if isnan(H).any():
            raise ValueError
        dH = (H.T * (self.Q_int + Q_ext_inf + Q_ext_pro)).T
        return dH

    def external_matrices(self, t, H):
        FOI_pro, FOI_inf = self.get_FOI_by_class(t, H)
        return build_external_import_matrix_SEPIRQ(
            self.household_population,
            FOI_pro,
            FOI_inf)

    def get_FOI_by_class(self, t, H):
        '''This calculates the age-stratified force-of-infection (FOI) on each
        household composition'''
        # Average number of each class by household
        denom = H.T.dot(self.composition_by_state)
        # Average detected infected by household in each class
        pro_by_class = zeros(shape(denom))
        # Only want to do states with positive denominator
        pro_by_class[denom > 0] = (
            H.T.dot(self.states_pro_only)[denom > 0]
            / denom[denom > 0]).squeeze()
        # Average undetected infected by household in each class
        inf_by_class = zeros(shape(denom))
        inf_by_class[denom > 0] = (
            H.T.dot(self.states_inf_only)[denom > 0]
            / denom[denom > 0]).squeeze()
        # This stores the rates of generating an infected of each class in
        # each state
        FOI_pro = self.states_sus_only.dot(
            diag(self.pro_trans_matrix.dot(
                self.epsilon * pro_by_class.T
                +
                self.import_model.detected(t))))
        FOI_inf = self.states_sus_only.dot(
            diag(self.inf_trans_matrix.dot(
                self.epsilon * inf_by_class.T
                +
                self.import_model.undetected(t))))

        return FOI_pro, FOI_inf

class SEIRRateEquations:
    '''This class represents a functor for evaluating the rate equations for
    the model with no imports of infection from outside the population. The
    state of the class contains all essential variables'''
    # pylint: disable=invalid-name
    def __init__(self,
                 model_input,
                 household_population,
                 epsilon=1.0,        # TODO: this needs a better name
                 no_compartments=4
                 ):

        self.household_population = household_population
        self.epsilon = epsilon
        self.Q_int = household_population.Q_int
        # To define external mixing we need to set up the transmission
        # matrices.
        # Scale rows of contact matrix by
        self.inf_trans_matrix = diag(model_input.sus).dot(model_input.k_ext)
        # age-specific susceptibilities
        # Scale columns by asymptomatic reduction in transmission
        # This stores number in each age class by household
        self.composition_by_state = household_population.composition_by_state
        # ::5 gives columns corresponding to susceptible cases in each age
        # class in each state
        self.states_sus_only = household_population.states[:, ::no_compartments]

        self.s_present = where(self.states_sus_only.sum(axis=1) > 0)[0]
        # 2::5 gives columns corresponding to detected cases in each age class
        # 4:5:end gives columns corresponding to undetected cases in each age
        # class in each state
        self.states_inf_only = household_population.states[:, 2::no_compartments]
        self.states_rec_only = household_population.states[:, 3::no_compartments]
        self.epsilon = epsilon
        self.import_model = model_input.import_model

        self.no_infs = where(self.states_inf_only.sum(axis=1) == 0)[0]

    def __call__(self, t, H):
        '''hh_ODE_rates calculates the rates of the ODE system describing the
        household ODE model'''
        Q_ext_inf = self.external_matrices(t, H)

        dH_ext = H.T * Q_ext_inf

        if (H<0).any():
            H[where(H<0)[0]]=0
        if isnan(H).any():
            raise ValueError('NaNs inside the state vector')
        dH = (H.T * (self.Q_int + Q_ext_inf)).T
        return dH

    def external_matrices(self, t, H):
        FOI_inf = self.get_FOI_by_class(t, H)
        return build_external_import_matrix_SEIR(
            self.household_population,
            FOI_inf)

    def get_FOI_by_class(self, t, H):
        '''This calculates the age-stratified force-of-infection (FOI) on each
        household composition'''
        # Average number of each class by household
        denom = H.T.dot(self.composition_by_state)
        # Average detected infected by household in each class
        # Average undetected infected by household in each class
        inf_by_class = zeros(shape(denom))
        inf_by_class[denom > 0] = (
            H.T.dot(self.states_inf_only)[denom > 0]
            / denom[denom > 0]).squeeze()
        FOI_inf = self.states_sus_only.dot(
            diag(self.inf_trans_matrix.dot(
                self.epsilon * inf_by_class.T
                +
                self.import_model.undetected(t))))

        return FOI_inf

def build_external_import_matrix_SEIR(
        household_population, FOI_inf):
    '''Gets sparse matrices containing rates of external infection in a
    household of a given type'''

    row = household_population.inf_event_row
    col = household_population.inf_event_col
    inf_class = household_population.inf_event_class
    total_size = len(household_population.which_composition)

    # Figure out which class gets infected in this transition
    i_vals = FOI_inf[row, inf_class]

    matrix_shape = (total_size, total_size)
    Q_ext_i = sparse(
        (i_vals, (row, col)),
        shape=matrix_shape)

    diagonal_idexes = (arange(total_size), arange(total_size))
    S = Q_ext_i.sum(axis=1).getA().squeeze()
    Q_ext_i += sparse((-S, diagonal_idexes))

    return Q_ext_i
