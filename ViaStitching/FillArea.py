#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#  FillArea.py
#
#  Copyright 2017 JS Reynaud <js.reynaud@gmail.com>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.

from __future__ import print_function
from pcbnew import *
import sys
import tempfile
import shutil
import os
import random
import math
import pprint
import wx


def wxPrint(msg):
    wx.LogMessage(msg)


#
if sys.version[0] == '2':  # maui
    xrange
else:
    xrange = range


"""
#  This script fills all areas of a specific net with Vias (Via Stitching)
#
#
# Usage in pcbnew's python console:
#  First you neet to copy this file (named FillArea.py) in your kicad_plugins
# directory (~/.kicad_plugins/ on Linux)
# Launch pcbnew and open python console (last entry of Tools menu)
# Then enter the following line (one by one, Hit enter after each)
import FillArea
FillArea.FillArea().Run()


# Other example:
# You can add modifications to parameters by adding functions calls:
FillArea.FillArea().SetDebug().SetNetname("GND").SetStepMM(1.27).SetSizeMM(0.6).SetDrillMM(0.3).SetClearanceMM(0.2).Run()

# with
# SetDebug: Activate debug mode (print evolution of the board in ascii art)
# SetNetname: Change the netname to consider for the filling
# (default is /GND or fallback to GND)
# SetStepMM: Change step between Via (in mm)
# SetSizeMM: Change Via copper size (in mm)
# SetDrillMM: Change Via drill hole size (in mm)
# SetClearanceMM: Change clearance for Via (in mm)

#  You can also use it in command line. In this case, the first parameter is
# the pcb file path. Default options are applied.
"""


class FillStrategy:
    def __init__(self, x_range, y_range, valid_predicate, centre_spacing):
        self.x_range = x_range
        self.y_range = y_range
        self.valid_predicate = valid_predicate
        self.centre_spacing = centre_spacing
    
    def generate_points(self):
        raise NotImplementedError


class GridFillStrategy(FillStrategy):
    def generate_points(self):
        x_steps = int((self.x_range[1] - self.x_range[0]) / self.centre_spacing) + 1
        y_steps = int((self.y_range[1] - self.y_range[0]) / self.centre_spacing) + 1

        points = []
        for x_i in range(x_steps):
            for y_i in range(y_steps):
                x = int(round(x_i * self.centre_spacing + self.x_range[0]))
                y = int(round(y_i * self.centre_spacing + self.y_range[0]))
                if self.valid_predicate(x, y):
                    points.append((x, y))
        
        return points


class StarFillStrategy(FillStrategy):
    def generate_points(self):
        # x spacing is 2 * spacing / sqrt(2), y spacing is spacing / sqrt(2)
        spacing = self.centre_spacing / math.sqrt(2)
        x_steps = int((self.x_range[1] - self.x_range[0]) / (2 * spacing)) + 1
        y_steps = int((self.y_range[1] - self.y_range[0]) / spacing) + 1

        points = []
        for x_i in range(x_steps):
            for y_i in range(y_steps):
                x = int(round(x_i * 2 * spacing + self.x_range[0] + (spacing if y_i % 2 else 0.0)))
                y = int(round(y_i * spacing + self.y_range[0]))
                if self.valid_predicate(x, y):
                    points.append((x, y))
        
        return points


class BridsonFillStrategy(FillStrategy):
    """
    This fill stragegy implements Bridsons Poisson disc sampling algorithm to generate
    randomly spaced points that are roughly uniformly spaced.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.k = 10

        # Start with a grid we can use for localised searching. Cell spacing is centre_spacing / sqrt(2)
        # such that no more than one point can end up in a cell.
        self._cell_size = self.centre_spacing / math.sqrt(2)
        self._x_steps = int((self.x_range[1] - self.x_range[0]) / self._cell_size)
        self._y_steps = int((self.y_range[1] - self.y_range[0]) / self._cell_size)
        self._checked = [[False] * self._x_steps for i in range(self._y_steps)]
        self._points = [[None] * self._x_steps for i in range(self._y_steps)]


    def generate_points(self):
        active = []
        for i in range(self._y_steps):
            for j in range(self._x_steps):
                if self._checked[i][j]:
                    continue
                else:
                    # Generate up to k random points in this cell until one is valid.
                    for _ in range(self.k):
                        point = self._generate_random_point_in_cell(i, j)
                        if self._is_valid(point):
                            self._points[i][j] = point
                            active.append(point)
                            break
                    self._checked[i][j] = True
                
                while active:
                    # If we have active points, do the Poisson disc sampling
                    base = active.pop()
                    random_points = self._generate_bridson_points(base)
                    for point in random_points:
                        if self._is_valid(point):
                            x_i, y_i = self._cell_index(point)
                            self._points[y_i][x_i] = point
                            active.append(point)
                            self._checked[y_i][x_i] = True

        
        points = []
        for row in self._points:
            for point in row:
                if point:
                    points.append(point)
        
        return points
    
    def _cell_index(self, point):
        x_i = math.floor((point[0] - self.x_range[0]) / self._cell_size)
        y_i = math.floor((point[1] - self.y_range[0]) / self._cell_size)
        return (x_i, y_i)
    
    def _is_valid(self, point):
        # Get the cell index for this point
        x_i, y_i = self._cell_index(point)

        # Check we're in bounds
        if x_i < 0 or x_i >= self._x_steps or y_i < 0 or y_i >= self._y_steps:
            return False
        
        # Check there isn't already a point in this cell
        if self._points[y_i][x_i]:
            return False
        
        # Check surrounding points
        OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1),
                   (-2, -1), (-2, 0), (-2, 1), (-1, 2), (0, 2), (1, 2), (2, 1), (2, 0), (2, -1), (1, -2), (0, -2), (-1, -2))
        for ox_i, oy_i in OFFSETS:
            px_i = x_i + ox_i
            py_i = y_i + oy_i
            if px_i < 0 or px_i >= self._x_steps or py_i < 0 or py_i >= self._y_steps:
                continue
            nbr = self._points[py_i][px_i]
            if nbr and math.sqrt((nbr[0] - point[0]) ** 2 + (nbr[1] - point[1]) ** 2) < self.centre_spacing:
                return False
        
        # Finally, check the predicate
        return self.valid_predicate(*point)
    
    def _generate_random_point_in_cell(self, i, j):
        x = self.x_range[0] + (j + random.random()) * self._cell_size
        y = self.y_range[0] + (i + random.random()) * self._cell_size
        return (int(round(x)), int(round(y)))
    
    def _generate_bridson_points(self, base):
        points = []
        for j in range(self.k):
            r = math.sqrt(3 * random.random() + 1) * self.centre_spacing
            th = random.uniform(0, 2 * math.pi)
            points.append((int(round(base[0] + r * math.sin(th))), int(round(base[1] + r * math.cos(th)))))
        return points
    
    def _generate_roberts_points(self, base):
        points = []
        r = self.centre_spacing + 2
        seed = random.uniform(0, 2 * math.pi)
        for j in range(self.k):
            th = 2 * math.pi * j / self.k + seed
            points.append((int(round(base[0] + r * math.sin(th))), int(round(base[1] + r * math.cos(th)))))
        return points

class FillArea:

    """
    Automaticaly add via on area where there are no track/existing via,
    pads and keepout areas
    """

    def __init__(self, filename=None):
        self.filename = None
        self.clearance = 0
        # Net name to use
        self.SetPCB(GetBoard())
        # Set the filename
        self.SetFile(filename)
        # Step between via
        self.SetStepMM(2.54)
        # Size of the via (diameter of copper)
        self.SetSizeMM(0.46)
        # Size of the drill (diameter)
        self.SetDrillMM(0.20)
        # Isolation between via and other elements
        # ie: radius from the border of the via
        self.SetClearanceMM(0.2)
        self.only_selected_area = False
        self.delete_vias = False
        if self.pcb is not None:
            for lnet in ["GND", "/GND"]:
                if self.pcb.FindNet(lnet) is not None:
                    self.SetNetname(lnet)
                    break
        self.netname = None
        self.debug = False
        self.random = False
        self.star = False
        if self.netname is None:
            self.SetNetname("GND")

        self.tmp_dir = None

    def SetFile(self, filename):
        self.filename = filename
        if self.filename:
            self.SetPCB(LoadBoard(self.filename))

    def SetDebug(self):
        wxPrint("Set debug")
        self.debug = True
        return self

    def SetRandom(self, r):
        random.seed()
        self.random = r
        return self

    def SetStar(self):
        self.star = True
        return self

    def SetPCB(self, pcb):
        self.pcb = pcb
        if self.pcb is not None:
            self.pcb.BuildListOfNets()
        return self

    def SetNetname(self, netname):
        self.netname = netname  # .upper()
        # wx.LogMessage(self.netname)
        return self

    def SetStepMM(self, s):
        self.step = float(FromMM(s))
        return self

    def SetSizeMM(self, s):
        self.size = float(FromMM(s))
        return self

    def SetDrillMM(self, s):
        self.drill = float(FromMM(s))
        return self

    def OnlyOnSelectedArea(self):
        self.only_selected_area = True
        return self

    def DeleteVias(self):
        self.delete_vias = True
        return self

    def SetClearanceMM(self, s):
        self.clearance = float(FromMM(s))
        return self

    def AddVia(self, position):
        m = VIA(self.pcb)
        m.SetPosition(position)
        m.SetNet(self.pcb.FindNet(self.netname))
        m.SetViaType(VIA_THROUGH)
        m.SetDrill(int(self.drill))
        m.SetWidth(int(self.size))
        # again possible to mark via as own since no timestamp_t binding kicad v5.1.4
        m.SetTimeStamp(33)  # USE 33 as timestamp to mark this via as generated by this script
        #wx.LogMessage('adding vias')
        self.pcb.Add(m)

    def RefillBoardAreas(self):
        for i in range(self.pcb.GetAreaCount()):
            area = self.pcb.GetArea(i)
            area.ClearFilledPolysList()
            area.UnFill()
        filler = ZONE_FILLER(self.pcb)
        filler.Fill(self.pcb.Zones())

    def Run(self):
        """
        Launch the process
        """

        if self.delete_vias:
            self._delete_vias()
            return
        
        # Get target areas for all layers, and move them off the PCB.
        target_areas = self._get_areas_on_copper(self.netname, self.only_selected_area)
        move_vector = wxPoint(self.pcb.GetBoundingBox().GetWidth() * 2, self.pcb.GetBoundingBox().GetHeight() * 2)
        for areas in target_areas.values():
            for area in areas:
                area.Move(move_vector)

        # Get the allowed polygons for via placement on all layers (which should include the target polygons)
        allowed_polys = self._get_allowed_polys()
        
        # Move target areas back, set them to "No Net" and refill. That way we'll get target placement
        # areas which include islands.
        target_areas = self._get_areas_on_copper(self.netname, self.only_selected_area)
        move_vector = wxPoint(-move_vector.x, -move_vector.y)
        no_net = self.pcb.GetNetsByName()['']
        for areas in target_areas.values():
            for area in areas:
                area.SetNet(no_net)
                area.Move(move_vector)
                area.SetTimeStamp(34)
        self.RefillBoardAreas()

        # Get target polygons for each layer
        target_areas = self._get_areas_on_copper('', self.only_selected_area, 34)
        target_polys = {}
        for layer_id, areas in target_areas.items():
            target_poly = SHAPE_POLY_SET()
            for area in areas:
                area_poly = SHAPE_POLY_SET(area.GetFilledPolysList(), True)
                area_poly.Inflate(area.GetMinThickness() // 2, 36)
                target_poly.BooleanAdd(poly, SHAPE_POLY_SET.PM_STRICTLY_SIMPLE)
            target_poly.Inflate(-int(round(self.clearance + self.size / 2)), 36)
            target_polys[layer_id] = target_poly

        '''
        # Search for areas on top/bottom layers
        all_areas = [self.pcb.GetArea(i) for i in xrange(self.pcb.GetAreaCount())]
        top_areas = filter(lambda x: (x.GetNetname() == '' and x.IsOnLayer(F_Cu) and not x.GetIsKeepout()), all_areas)
        bot_areas = filter(lambda x: (x.GetNetname() == '' and x.IsOnLayer(B_Cu) and not x.GetIsKeepout()), all_areas)
        
        # Calculate where it'd be valid to put vias that hit both top/bottom layers in the
        # filled areas, without the annulus going outside of them.
        valid = self._get_valid_placement_area(top_areas)
        valid.BooleanIntersection(self._get_valid_placement_area(bot_areas), SHAPE_POLY_SET.PM_STRICTLY_SIMPLE)
        
        # Place vias in a grid wherever we can.
        bounds = self.pcb.GetBoundingBox()
        x_range = (bounds.GetLeft(), bounds.GetRight())
        y_range = (bounds.GetTop(), bounds.GetBottom())
        valid_predicate = lambda x, y: valid.Contains(VECTOR2I(x, y))
        if self.random:
            strategy = BridsonFillStrategy
        elif self.star:
            strategy = StarFillStrategy
        else:
            strategy = GridFillStrategy
        points = strategy(x_range, y_range, valid_predicate, self.step).generate_points()
        for x, y in points:
            self.AddVia(wxPoint(x, y))

        # Reset target area nets to original and refill
        all_areas = [self.pcb.GetArea(i) for i in xrange(self.pcb.GetAreaCount())]
        target_areas = filter(lambda x: (x.GetNetname() == '' and (x.IsOnLayer(F_Cu) or x.IsOnLayer(B_Cu)) and not x.GetIsKeepout()), all_areas)
        for area in target_areas:
            area.SetNet(self.pcb.GetNetsByName()[self.netname])
        self.RefillBoardAreas()
        '''
    
    def _delete_vias(self):
        target_tracks = filter(lambda x: (x.GetNetname() == self.netname), self.pcb.GetTracks())
        target_tracks_cp = list(target_tracks)
        l = len (target_tracks_cp)
        for i in range(l):
            if target_tracks_cp[i].Type() == PCB_VIA_T:
                if target_tracks_cp[i].GetTimeStamp() == 33:
                    self.pcb.RemoveNative(target_tracks_cp[i])
        self.RefillBoardAreas()
    
    def _get_valid_placement_area(self, areas):
        # Get some polygons for top/bottom with a buffer.
        valid = SHAPE_POLY_SET()

        for area in areas:
            # Clone and inflate polys by the min width / 2. KiCAD seems to store them as polygons
            # with a line width, not as polys with a 0 line width.
            poly = SHAPE_POLY_SET(area.GetFilledPolysList(), True)
            poly.Inflate(area.GetMinThickness() // 2, 36)
            valid.BooleanAdd(poly, SHAPE_POLY_SET.PM_STRICTLY_SIMPLE)
        
        # Deflate by our via radius + clearance, and we have polygon encompassing where we can
        # place via centers on the top.
        valid.Inflate(-int(round(self.clearance + self.size / 2)), 36)

        return valid
    
    def _get_allowed_polys(self):
        bounds = self.pcb.GetBoundingBox()

        for layer_id in self.pcb.GetEnabledLayers().CuStack():
            area = self.pcb.AddArea(None, 0, layer_id, wxPoint(bounds.GetLeft(), bounds.GetTop()), ZONE_CONTAINER.NO_HATCH)
            area.AppendCorner(wxPoint(bounds.GetRight(), bounds.GetTop()), -1)
            area.AppendCorner(wxPoint(bounds.GetRight(), bounds.GetBottom()), -1)
            area.AppendCorner(wxPoint(bounds.GetLeft(), bounds.GetBottom()), -1)
            area.SetTimeStamp(34)
            area.SetMinThickness(FromMM(0.4))
            area.SetThermalReliefCopperBridge(FromMM(0.4))
            area.SetZoneClearance(0)
            area.SetThermalReliefGap(0)
            area.SetPadConnection(0)
        
        self.RefillBoardAreas()

        allowed = None
        for areas in self._get_areas_on_copper('', False, 34).values():
            for area in areas:
                poly = SHAPE_POLY_SET(area.GetFilledPolysList(), True)
                poly.Inflate(FromMM(0.2), 36)
                if allowed is None:
                    allowed = poly
                else:
                    allowed.BooleanIntersection(poly, SHAPE_POLY_SET.PM_STRICTLY_SIMPLE)
                self.pcb.RemoveArea(None, area)
        
        allowed.Inflate(-int(round(self.clearance + self.size / 2)), 36)

        return allowed
    
    def _get_areas_on_copper(self, net_name=None, only_selected=False, timestamp=None):
        predicate = lambda x: (
            (net_name is None or x.GetNetname() == net_name) and
            (timestamp is None or x.GetTimeStamp() == timestamp) and
            x.IsOnCopperLayer() and
            not x.GetIsKeepout() and
            (x.IsSelected() or not only_selected)
        )

        copper_layer_ids = set(self.pcb.GetEnabledLayers().CuStack())

        areas = {layer_id: [] for layer_id in copper_layer_ids}
        for area in filter(predicate, (self.pcb.GetArea(i) for i in xrange(self.pcb.GetAreaCount()))):
            areas[area.GetLayer()].append(area)
        
        return areas



if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: %s <KiCad pcb filename>" % sys.argv[0])
    else:
        import sys
        FillArea(sys.argv[1]).SetDebug().Run()
