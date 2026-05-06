import argparse
import json
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

DEFAULT_SCENARIO_PATH = "benchmark/base_city_world.json"


def load_world(filepath):
    """Loads the RescueBench JSON world file."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find '{filepath}'.")
        return None

def find_nearest_free_lattice_cell(target_cell, occupied_cells):
    """Finds the nearest unoccupied lattice cell using Manhattan-radius expansion."""
    if target_cell not in occupied_cells:
        return target_cell

    target_x, target_y = target_cell
    for radius in range(1, 256):
        candidates = []
        for dx in range(-radius, radius + 1):
            dy = radius - abs(dx)
            candidates.append((target_x + dx, target_y + dy))
            if dy != 0:
                candidates.append((target_x + dx, target_y - dy))

        candidates.sort(key=lambda cell: (abs(cell[0] - target_x) + abs(cell[1] - target_y), cell[1], cell[0]))
        for cell in candidates:
            if cell not in occupied_cells:
                return cell

    # Extremely unlikely fallback.
    return (target_x + 256, target_y)

def build_city_grid_layout(graph, spacing=4.0, component_gap_cells=4):
    """
    Builds a generic lattice layout for any city graph without hardcoded node IDs.
    Nodes are snapped to unique grid cells after an initial structure-aware layout.
    """
    if graph.number_of_nodes() == 0:
        return {}

    undirected_graph = graph.to_undirected()
    positions = {}
    x_offset_cells = 0

    components = sorted(nx.connected_components(undirected_graph), key=lambda nodes: (-len(nodes), sorted(nodes)[0]))
    for component_nodes in components:
        component = undirected_graph.subgraph(component_nodes).copy()

        if component.number_of_nodes() == 1:
            single_node = next(iter(component.nodes))
            positions[single_node] = (x_offset_cells * spacing, 0.0)
            x_offset_cells += component_gap_cells
            continue

        try:
            initial_pos = nx.planar_layout(component)
        except nx.NetworkXException:
            layout_k = max(0.35, 1.8 / (component.number_of_nodes() ** 0.5))
            initial_pos = nx.spring_layout(component, seed=42, k=layout_k, iterations=500)

        x_values = [initial_pos[node][0] for node in component.nodes]
        y_values = [initial_pos[node][1] for node in component.nodes]
        min_x, max_x = min(x_values), max(x_values)
        min_y, max_y = min(y_values), max(y_values)

        # Pick a compact lattice size for the component.
        node_count = component.number_of_nodes()
        lattice_width = max(3, int(round(node_count ** 0.5)) + 1)
        lattice_height = max(3, (node_count + lattice_width - 1) // lattice_width + 1)

        occupied_cells = set()
        component_cells = {}
        priority_nodes = sorted(
            component.nodes,
            key=lambda node: (-component.degree[node], initial_pos[node][0], initial_pos[node][1], str(node))
        )

        for node in priority_nodes:
            raw_x, raw_y = initial_pos[node]
            norm_x = 0.5 if max_x == min_x else (raw_x - min_x) / (max_x - min_x)
            norm_y = 0.5 if max_y == min_y else (raw_y - min_y) / (max_y - min_y)
            target_cell = (
                int(round(norm_x * (lattice_width - 1))),
                int(round(norm_y * (lattice_height - 1)))
            )
            lattice_cell = find_nearest_free_lattice_cell(target_cell, occupied_cells)
            occupied_cells.add(lattice_cell)
            component_cells[node] = lattice_cell

        component_min_y = min(cell[1] for cell in component_cells.values())
        component_max_y = max(cell[1] for cell in component_cells.values())
        y_center = (component_min_y + component_max_y) / 2.0

        component_width_cells = max(cell[0] for cell in component_cells.values()) + 1
        for node, (cell_x, cell_y) in component_cells.items():
            positions[node] = ((x_offset_cells + cell_x) * spacing, (cell_y - y_center) * spacing)

        x_offset_cells += component_width_cells + component_gap_cells

    return positions

def iter_path_segments(path_points):
    """Yields consecutive line segments from a polyline path."""
    for idx in range(len(path_points) - 1):
        yield path_points[idx], path_points[idx + 1]

def normalize_segment_key(start_point, end_point):
    """Returns an order-invariant key for a segment."""
    start = (round(start_point[0], 4), round(start_point[1], 4))
    end = (round(end_point[0], 4), round(end_point[1], 4))
    return (start, end) if start <= end else (end, start)

def path_total_length(path_points):
    """Returns total Euclidean length of a polyline path."""
    total = 0.0
    for start, end in iter_path_segments(path_points):
        total += ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return total

def build_edge_path_candidates(source_pos, target_pos, grid_step):
    """
    Returns orthogonal route candidates.
    For already aligned nodes, includes small dogleg alternatives to reduce overlap.
    """
    src_x, src_y = source_pos
    dst_x, dst_y = target_pos

    if src_x == dst_x and src_y == dst_y:
        return [[source_pos, target_pos]]

    candidates = []
    lane_offset = grid_step * 0.42
    lane_offsets = [lane_offset, -lane_offset, lane_offset * 2.0, -lane_offset * 2.0]

    if src_x != dst_x and src_y != dst_y:
        candidates.append([source_pos, (dst_x, src_y), target_pos])
        candidates.append([source_pos, (src_x, dst_y), target_pos])
        for offset in lane_offsets:
            # Horizontal-first detour lane.
            candidates.append([
                source_pos,
                (src_x, src_y + offset),
                (dst_x, src_y + offset),
                (dst_x, dst_y),
                target_pos
            ])
            # Vertical-first detour lane.
            candidates.append([
                source_pos,
                (src_x + offset, src_y),
                (src_x + offset, dst_y),
                (dst_x, dst_y),
                target_pos
            ])
    else:
        lane_offsets = [0.0] + lane_offsets
        if src_y == dst_y:
            for offset in lane_offsets:
                if offset == 0:
                    candidates.append([source_pos, target_pos])
                else:
                    candidates.append([source_pos, (src_x, src_y + offset), (dst_x, dst_y + offset), target_pos])
        else:
            for offset in lane_offsets:
                if offset == 0:
                    candidates.append([source_pos, target_pos])
                else:
                    candidates.append([source_pos, (src_x + offset, src_y), (dst_x + offset, dst_y), target_pos])

    unique_candidates = []
    seen = set()
    for path in candidates:
        simplified_path = []
        for point in path:
            if not simplified_path or point != simplified_path[-1]:
                simplified_path.append(point)
        key = tuple((round(x, 4), round(y, 4)) for x, y in simplified_path)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(simplified_path)

    return unique_candidates

def score_path_overlap(path_points, segment_usage):
    """Scores a candidate path by how much it overlaps already-used segments."""
    overlap = 0
    for start, end in iter_path_segments(path_points):
        overlap += segment_usage.get(normalize_segment_key(start, end), 0)
    return overlap

def register_path_usage(path_points, segment_usage):
    """Registers segments of a chosen path so later edges can avoid them."""
    for start, end in iter_path_segments(path_points):
        key = normalize_segment_key(start, end)
        segment_usage[key] = segment_usage.get(key, 0) + 1

def point_on_axis_aligned_segment(point, segment_start, segment_end, tol=1e-6):
    """Returns True if point lies on an axis-aligned segment (including endpoints)."""
    px, py = point
    x1, y1 = segment_start
    x2, y2 = segment_end

    if abs(x1 - x2) <= tol:
        return abs(px - x1) <= tol and min(y1, y2) - tol <= py <= max(y1, y2) + tol
    if abs(y1 - y2) <= tol:
        return abs(py - y1) <= tol and min(x1, x2) - tol <= px <= max(x1, x2) + tol
    return False

def count_path_node_collisions(path_points, source_node, target_node, positions):
    """
    Counts non-endpoint nodes whose centers lie on the routed edge path.
    These are visually misleading because they look like extra intersections.
    """
    collisions = 0
    for node_id, node_point in positions.items():
        if node_id in (source_node, target_node):
            continue
        if any(point_on_axis_aligned_segment(node_point, start, end) for start, end in iter_path_segments(path_points)):
            collisions += 1
    return collisions

def polyline_midpoint(path_points):
    """Returns the midpoint along a polyline path."""
    if len(path_points) < 2:
        return path_points[0]

    segment_lengths = []
    total_length = 0.0
    for i in range(len(path_points) - 1):
        x1, y1 = path_points[i]
        x2, y2 = path_points[i + 1]
        seg_len = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        segment_lengths.append(seg_len)
        total_length += seg_len

    halfway = total_length / 2.0
    walked = 0.0
    for i, seg_len in enumerate(segment_lengths):
        if walked + seg_len >= halfway and seg_len > 0:
            x1, y1 = path_points[i]
            x2, y2 = path_points[i + 1]
            ratio = (halfway - walked) / seg_len
            return (x1 + ratio * (x2 - x1), y1 + ratio * (y2 - y1))
        walked += seg_len

    return path_points[-1]

def visualize_world(world_data):
    """Parses the JSON data and visualizes it as a NetworkX graph."""
    if not world_data:
        return

    # 1. Initialize the Directed Graph
    G = nx.DiGraph()

    # 2. Track where incidents and fleet units are located
    node_annotations = {}
    
    vehicle_tag_map = {
        'police_car': '[POL]',
        'ambulance': '[AMB]',
        'fire_engine': '[FIRE]'
    }

    for unit in world_data.get('active_fleet', []):
        loc = unit['current_location']
        tag = vehicle_tag_map.get(unit['vehicle_type'], '[TRUCK]')
        ann = f"{tag} {unit['unit_id']}"
        node_annotations.setdefault(loc, []).append(ann)
        
    for incident in world_data.get('incidents', []):
        loc = incident['location_node']
        ann = f"[INC] {incident['incident_id']} S:{incident['severity_weight']}"
        node_annotations.setdefault(loc, []).append(ann)

    # 3. Add Nodes to Graph
    # Color mapping for node types
    color_map = {
        "depot": "lightblue",
        "hospital": "lightcoral",
        "gas_station": "gold",
        "standard_intersection": "lightgray"
    }
    
    node_colors = []
    node_sizes = []
    labels = {}
    
    for node in world_data.get('nodes', []):
        G.add_node(node['id'], type=node['type'], capacity=node['current_capacity'])
        
        # Determine color based on type
        node_colors.append(color_map.get(node['type'], "white"))
        
        # Build label string (Node ID + Capacity + Annotations)
        display_id = node['id'].replace("node_", "")
        label = f"{display_id}\n(Cap: {node['current_capacity']})"
        if node['id'] in node_annotations:
            label += "\n" + "\n".join(node_annotations[node['id']])
        labels[node['id']] = label

        # Scale node size to label density so multi-line labels stay inside.
        line_count = label.count("\n") + 1
        extra_lines = max(0, line_count - 2)
        node_sizes.append(min(9000, 3200 + extra_lines * 1150))

    # 4. Add Edges to Graph
    edge_color_map = {
        "clear": "darkgray",
        "blocked_by_debris": "red",
        "flooded": "dodgerblue"
    }
    
    edge_draw_data = []
    edge_status_short = {
        "blocked_by_debris": "BLOCKED",
        "flooded": "FLOODED"
    }
    
    for edge in world_data.get('edges', []):
        G.add_edge(edge['source_node'], edge['target_node'], weight=edge['base_travel_time'])
        status = edge['status']
        edge_color = edge_color_map.get(status, "black")
        
        # Label shows travel time and if there's a restriction/blockage
        edge_lbl = f"Time:{edge['base_travel_time']}"
        if status != "clear":
            edge_lbl += f"\n[{edge_status_short.get(status, status.upper())}]"
        edge_draw_data.append({
            "source": edge['source_node'],
            "target": edge['target_node'],
            "color": edge_color,
            "label": edge_lbl
        })

    # 5. Drawing the Graph
    plt.figure(figsize=(22, 13))
    plt.title(f"{world_data['metadata']['scenario_name']} (Time: {world_data['metadata']['global_clock_min']})", fontsize=16, fontweight='bold')
    
    # Generate a generic lattice layout with orthogonal-friendly spacing.
    grid_step = 4.0
    pos = build_city_grid_layout(G, spacing=grid_step)

    # Subtle map grid backdrop to mimic city blocks.
    ax = plt.gca()
    ax.set_facecolor("#f3f4f6")
    min_x = min(x for x, _ in pos.values()) - 2.0
    max_x = max(x for x, _ in pos.values()) + 2.0
    min_y = min(y for _, y in pos.values()) - 2.0
    max_y = max(y for _, y in pos.values()) + 2.0

    x = min_x
    while x <= max_x:
        ax.axvline(x=x, color="white", linewidth=0.8, zorder=0)
        x += grid_step
    y = min_y
    while y <= max_y:
        ax.axhline(y=y, color="white", linewidth=0.8, zorder=0)
        y += grid_step

    # Pick orthogonal routes with overlap avoidance so labels/roads stay readable.
    segment_usage = {}
    for edge_data in edge_draw_data:
        source_pos = pos[edge_data["source"]]
        target_pos = pos[edge_data["target"]]
        candidate_paths = build_edge_path_candidates(source_pos, target_pos, grid_step)
        edge_data["path"] = min(
            candidate_paths,
            key=lambda path: (
                count_path_node_collisions(path, edge_data["source"], edge_data["target"], pos),
                score_path_overlap(path, segment_usage),
                len(path),
                path_total_length(path)
            )
        )
        register_path_usage(edge_data["path"], segment_usage)

    # Draw edges as road-like paths.
    edge_label_collision_count = {}
    for edge_data in edge_draw_data:
        edge_path = edge_data["path"]
        x_coords = [point[0] for point in edge_path]
        y_coords = [point[1] for point in edge_path]
        ax.plot(x_coords, y_coords, color=edge_data["color"], linewidth=2.7, zorder=1, solid_capstyle='round')
        if len(edge_path) >= 2:
            arrow_start = edge_path[-2]
            arrow_end = edge_path[-1]
            ax.annotate(
                "",
                xy=arrow_end,
                xytext=arrow_start,
                arrowprops={
                    "arrowstyle": "-|>",
                    "color": edge_data["color"],
                    "lw": 1.0,
                    "mutation_scale": 11
                },
                zorder=2
            )

        label_x, label_y = polyline_midpoint(edge_path)
        first_segment_horizontal = edge_path[0][1] == edge_path[1][1]
        if first_segment_horizontal:
            label_y += 0.22
        else:
            label_x += 0.22

        # Nudge labels that land in similar spots to avoid stacking.
        label_key = (round(label_x, 1), round(label_y, 1))
        collision_index = edge_label_collision_count.get(label_key, 0)
        edge_label_collision_count[label_key] = collision_index + 1
        if collision_index:
            if first_segment_horizontal:
                label_y += 0.2 * collision_index
            else:
                label_x += 0.2 * collision_index

        ax.text(
            label_x,
            label_y,
            edge_data["label"],
            fontsize=6,
            color="#222222",
            ha='center',
            va='center',
            zorder=2,
            bbox={
                "boxstyle": "round,pad=0.12",
                "facecolor": "#f3f4f6",
                "edgecolor": edge_data["color"],
                "linewidth": 0.4,
                "alpha": 0.95
            }
        )

    # Draw Nodes above roads
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes, edgecolors='black')
    
    # Draw Node Labels
    nx.draw_networkx_labels(G, pos, labels, font_size=6, font_weight="bold")

    # 6. Create Legends
    # Node Type Legend
    node_legend_handles = [mpatches.Patch(color=color, label=ntype.replace('_', ' ').title()) for ntype, color in color_map.items()]
    legend1 = plt.legend(handles=node_legend_handles, title="Location Types", loc='upper left', bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0)
    plt.gca().add_artist(legend1)
    
    # Edge Status Legend
    edge_legend_handles = [mpatches.Patch(color=color, label=status.replace('_', ' ').title()) for status, color in edge_color_map.items()]
    plt.legend(
        handles=edge_legend_handles,
        title="Road Status",
        loc='upper left',
        bbox_to_anchor=(1.01, 0.64),
        borderaxespad=0.0
    )

    plt.tight_layout(rect=[0, 0, 0.8, 1]) # Reserve right-side column for legends
    plt.axis('off')
    
    print("Graph generated successfully! Displaying window...")
    plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize a RescueBench scenario JSON as a city graph.")
    parser.add_argument(
        "scenario_path",
        nargs="?",
        default=DEFAULT_SCENARIO_PATH,
        help=f"Path to scenario JSON file (default: {DEFAULT_SCENARIO_PATH})",
    )
    args = parser.parse_args()

    json_filepath = args.scenario_path
    world_data = load_world(json_filepath)
    if world_data:
        visualize_world(world_data)
