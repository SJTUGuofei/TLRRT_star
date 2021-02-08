# -*- coding: utf-8 -*-

"""
construct trees for unbiased sampling optimal task planning for multi-robots
"""

from random import uniform
from networkx.classes.digraph import DiGraph
from networkx.algorithms import dfs_labeled_edges
import math
import numpy as np
from collections import OrderedDict
import pyvisgraph as vg
from shapely.geometry import Point, LineString
from uniform_geometry import sample_uniform_geometry
from scipy.stats import truncnorm


class unbiasedTree(object):
    """
    unbiased tree for prefix and suffix parts
    """

    def __init__(self, workspace, buchi, init_state, init_label, segment, para):
        """
        initialization of the tree
        :param workspace: workspace
        :param buchi: buchi automaton
        :param init_state: initial location of the robots
        :param init_label: label generated by the initial location
        :param segment: prefix or suffix part
        :param para: parameters regarding unbiased-sampling method
        """
        # parameters regarding workspace
        self.workspace = workspace.workspace
        self.dim = len(self.workspace)
        self.regions = workspace.regions
        self.obstacles = workspace.obs
        self.robot = buchi.number_of_robots
        # parameters regarding task
        self.buchi = buchi
        self.accept = self.buchi.buchi_graph.graph['accept']
        self.init = init_state

        # initlizing the tree
        self.unbiased_tree = DiGraph(type='PBA', init=self.init)
        self.unbiased_tree.add_node(self.init, cost=0, label=init_label)

        # parameters regarding TL-RRT* algorithm
        self.goals = set()
        self.step_size = para['step_size']
        self.segment = segment
        self.lite = para['is_lite']
        # size of the ball used in function near
        uni_v = np.power(np.pi, self.robot * self.dim / 2) / math.gamma(self.robot * self.dim / 2 + 1)
        # self.gamma = np.ceil(4 * np.power(1 / uni_v, 1. / (self.dim * self.robot)))  # unit workspace
        self.gamma = (2 + 1 / 4) * np.power((1 + 0.0 / 4) * 2.5 / (self.dim * self.robot + 1) / (1 / 4) / (1 - 0.0)
                                             * 0.84 / uni_v, 1. / (self.dim * self.robot + 1))

        # select final buchi states
        if self.segment == 'prefix':
            self.b_final = self.buchi.buchi_graph.graph['accept'][0]
        else:
            self.b_final = self.buchi.buchi_graph.graph['accept']

        # threshold for collision avoidance
        self.threshold = para['threshold']


    def sample(self):
        """
        sample point from the workspace
        :return: sampled point, tuple
        """
        x_rand = []
        for i in range(self.dim):
            x_rand.append(uniform(0, self.workspace[i]))

        return tuple(x_rand)

    def collision_avoidance(self, x, robot_index):
        """
        check whether robots with smaller index than robot_index collide with the robot of index robot_index
        :param x: position of robots
        :param robot_index: index of the specific robot
        :return: true if collision free
        """
        for i in range(len(x)):
            if i != robot_index and np.fabs(x[i][0] - x[robot_index][0]) <= self.threshold and \
                            np.fabs(x[i][1] - x[robot_index][1]) <= self.threshold:
                return False
        return True

    def nearest(self, x_rand):
        """
        find the nearest class of vertices in the tree
        :param: x_rand randomly sampled point form: single point ()
        :return: nearest class of vertices form: single point ()
        """
        min_dis = math.inf
        q_p_nearest = []
        for node in self.unbiased_tree.nodes:
            x = self.mulp2single(node[0])
            dis = np.linalg.norm(np.subtract(x_rand, x))
            if dis < min_dis:
                q_p_nearest = [node]
                min_dis = dis
            elif dis == min_dis:
                q_p_nearest.append(node)
        return q_p_nearest

    def steer(self, x_rand, x_nearest):
        """
        steer
        :param: x_rand randomly sampled point form: single point ()
        :param: x_nearest nearest point in the tree form: single point ()
        :return: new point single point ()
        """
        if np.linalg.norm(np.subtract(x_rand, x_nearest)) <= self.step_size:
            return x_rand
        else:
            return tuple(map(tuple, np.asarray(x_nearest) + self.step_size * (np.subtract(x_rand, x_nearest)) /
                             np.linalg.norm(np.subtract(x_rand, x_nearest))))

    def extend(self, q_new, near_nodes, label, obs_check):
        """
        add the new sate q_new to the tree
        :param: q_new: new state
        :param: near_nodes: near state
        :param: obs_check: check the line connecting two points are inside the freespace
        :return: the tree after extension
        """
        added = False
        cost = np.inf
        q_min = ()
        # loop over all nodes in near_nodes
        for node in near_nodes:
            if q_new != node and obs_check[(q_new[0], node[0])] and \
                    self.check_transition_b(node[1], self.unbiased_tree.nodes[node]['label'], q_new[1]):
                c = self.unbiased_tree.nodes[node]['cost'] \
                    + np.linalg.norm(np.subtract(self.mulp2single(q_new[0]), self.mulp2single(node[0])))
                if c < cost:
                    added = True
                    q_min = node
                    cost = c
        if added:
            self.unbiased_tree.add_node(q_new, cost=cost, label=label)
            self.unbiased_tree.add_edge(q_min, q_new)
            if self.segment == 'prefix' and q_new[1] in self.accept:
                q_n = list(list(self.unbiased_tree.pred[q_new].keys())[0])
                cost = self.unbiased_tree.nodes[tuple(q_n)]['cost']
                label = self.unbiased_tree.nodes[tuple(q_n)]['label']
                q_n[1] = q_new[1]
                q_n = tuple(q_n)
                if q_n != q_min:
                    self.unbiased_tree.add_node(q_n, cost=cost, label=label)
                    self.unbiased_tree.add_edge(q_min, q_n)
                    self.goals.add(q_n)
            # if self.segment == 'suffix' and \
            #         self.obstacle_check([self.init], q_new[0], label)[(q_new[0], self.init[0])] \
            #         and self.check_transition_b(q_new[1], label, self.init[1]):
            #     self.goals.add(q_new)

            elif self.segment == 'suffix' and self.init[1] == q_new[1]:
                self.goals.add(q_new)
        return added

    def rewire(self, q_new, near_nodes, obs_check):
        """
        :param: q_new: new state
        :param: near_nodes: states returned near
        :param: obs_check: check whether obstacle-free
        :return: the tree after rewiring
        """
        for node in near_nodes:
            if obs_check[(q_new[0], node[0])] \
                    and self.check_transition_b(q_new[1], self.unbiased_tree.nodes[q_new]['label'], node[1]):
                c = self.unbiased_tree.nodes[q_new]['cost'] \
                    + np.linalg.norm(np.subtract(self.mulp2single(q_new[0]), self.mulp2single(node[0])))
                delta_c = self.unbiased_tree.nodes[node]['cost'] - c
                # update the cost of node in the subtree rooted at the rewired node
                if delta_c > 0:
                    self.unbiased_tree.remove_edge(list(self.unbiased_tree.pred[node].keys())[0], node)
                    self.unbiased_tree.add_edge(q_new, node)
                    edges = dfs_labeled_edges(self.unbiased_tree, source=node)
                    for _, v, d in edges:
                        if d == 'forward':
                            self.unbiased_tree.nodes[v]['cost'] = self.unbiased_tree.nodes[v]['cost'] - delta_c

    def near(self, x_new):
        """
        find the states in the near ball
        :param x_new: new point form: single point
        :return: p_near: near state, form: tuple (mulp, buchi)
        """
        near_nodes = []
        radius = min(
            self.gamma * np.power(np.log(self.unbiased_tree.number_of_nodes() + 1) / self.unbiased_tree.number_of_nodes(),
                                  1. / (self.dim * self.robot)), self.step_size)
        for node in self.unbiased_tree.nodes:
            if np.linalg.norm(np.subtract(x_new, self.mulp2single(node[0]))) <= radius:
                near_nodes.append(node)
        return near_nodes

    def obstacle_check(self, near_node, x_new, label):
        """
        check whether line from x_near to x_new is obstacle-free
        :param near_node: nodes returned by near function
        :param x_new: new position component
        :param label: label of x_new
        :return: a dictionary indicating whether the line connecting two points are obstacle-free
        """

        obs_check = {}
        checked = set()

        for node in near_node:
            # whether the position component of nodes has been checked
            if node[0] in checked:
                continue
            checked.add(node[0])
            obs_check[(x_new, node[0])] = True
            flag = True  # indicate whether break and jump to outer loop
            for r in range(self.robot):
                # the line connecting two points crosses an obstacle
                for (obs, boundary) in iter(self.obstacles.items()):
                    if LineString([Point(node[0][r]), Point(x_new[r])]).intersects(boundary):
                        obs_check[(x_new, node[0])] = False
                        flag = False
                        break
                # no need to check further
                if not flag:
                    break

                for (region, boundary) in iter(self.regions.items()):
                    if LineString([Point(node[0][r]), Point(x_new[r])]).intersects(boundary) \
                            and region + '_' + str(r + 1) != label[r] \
                            and region + '_' + str(r + 1) != self.unbiased_tree.nodes[node]['label'][r]:
                        obs_check[(x_new, node[0])] = False
                        flag = False
                        break
                # no need to check further
                if not flag:
                    break

        return obs_check

    def get_label(self, x):
        """
        generating the label of position component
        :param x: position
        :return: label
        """
        point = Point(x)
        # whether x lies within obstacle
        for (obs, boundary) in iter(self.obstacles.items()):
            if point.within(boundary):
                return obs

        # whether x lies within regions
        for (region, boundary) in iter(self.regions.items()):
            if point.within(boundary):
                return region
        # x lies within unlabeled region
        return ''

    def check_transition_b(self, q_b, x_label, q_b_new):
        """
        check whether q_b -- x_label ---> q_b_new
        :param q_b: buchi state
        :param x_label: label of x
        :param q_b_new: buchi state
        :return True if satisfied
        """
        b_state_succ = self.buchi.buchi_graph.succ[q_b]
        # q_b_new is not the successor of b_state
        if q_b_new not in b_state_succ:
            return False
        # check whether label of x enables the transition
        truth = self.buchi.buchi_graph.edges[(q_b, q_b_new)]['truth']
        if self.check_transition_b_helper(x_label, truth):
            return True

        return False

    def check_transition_b_helper(self, x_label, truth):
        """
        check whether transition enabled with current generated label
        :param x_label: label of the current position
        :param truth: symbol enabling the transition
        :return: true or false
        """
        if truth == '1':
            return True
        # all true propositions should be satisdied
        true_label = [true_label for true_label in truth.keys() if truth[true_label]]
        for label in true_label:
            if label not in x_label: return False

        # all fasle propositions should not be satisfied
        false_label = [false_label for false_label in truth.keys() if not truth[false_label]]
        for label in false_label:
            if label in x_label: return False

        return True

    def find_path(self, goals):
        """
        find the path backwards
        :param goals: found all goal states
        :return: the path leading to the goal state and the corresponding cost
        """
        paths = OrderedDict()
        for i in range(len(goals)):
            goals = list(goals)
            goal = goals[i]
            path = [goal]
            s = goal
            while s != self.init:
                s = list(self.unbiased_tree.pred[s].keys())[0]
                path.insert(0, s)
            if self.segment == 'prefix':
                paths[i] = [self.unbiased_tree.nodes[goal]['cost'], path]
            elif self.segment == 'suffix':
                path.append(self.init)
                paths[i] = [self.unbiased_tree.nodes[goal]['cost'] + np.linalg.norm(np.subtract(self.mulp2single(goal[0]),
                                                                                              self.mulp2single(
                                                                                                  self.init[0]))), path]

        return paths

    def mulp2single(self, point):
        """
        convert a point, which in the form of a tuple of tuple ((),(),(),...) to point in the form of a flat tuple
        :param point: point((position of robot 1), (position of robot2), (), ...)
        :return: point (position of robot1, position of robot2, ...)
        """
        return tuple([p for r in point for p in r])

    def single2mulp(self, point):
        """
        convert a point in the form of flat tuple to point in the form of a tuple of tuple ((),(),(),...)
        :param point: point (position of robot1, position of robot2, ...)
        :return:  point((position of robot 1), (position of robot2), (), ...)
        """
        mp = [point[i * self.dim:(i + 1) * self.dim] for i in range(self.robot)]
        return tuple(mp)
